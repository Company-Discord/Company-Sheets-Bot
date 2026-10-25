"""Optional roster sync and character links."""
import logging
import os
import asyncio
from datetime import datetime
from urllib.parse import urlsplit
import discord
from discord import app_commands
from discord.ext import commands, tasks

import aiohttp
from src.dashboard.aion import AionAdapter, AionError
from src.dashboard.repository import Conflict, Missing, Repository

log = logging.getLogger(__name__)
AION_REGIONS = [
    app_commands.Choice(name='North America East', value='nae'),
    app_commands.Choice(name='North America West', value='naw'),
    app_commands.Choice(name='Europe', value='eu'),
    app_commands.Choice(name='South America', value='sa'),
    app_commands.Choice(name='Asia', value='asia'),
    app_commands.Choice(name='Korea', value='kr'),
    app_commands.Choice(name='Taiwan', value='tw'),
]


def character_embed(character, *, source_text=None):
    data = character['data']
    title = f"{'⭐ ' if character['is_main'] else ''}{data.get('name') or 'AION 2 character'}"
    embed = discord.Embed(title=title[:256], color=discord.Color.from_rgb(190, 222, 153),
                         url=data.get('profile_url'))
    embed.description = ' · '.join(filter(None, [data.get('class_name'), data.get('server_name'), character.get('region', '').upper()]))
    embed.add_field(name='Level', value=str(data.get('level') if data.get('level') is not None else '—'), inline=True)
    embed.add_field(name='Combat power', value=f"{data['combat_power']:,}" if data.get('combat_power') is not None else '—', inline=True)
    embed.add_field(name='Item level', value=f"{data['item_level']:,}" if data.get('item_level') is not None else '—', inline=True)
    if data.get('equipment'):
        lines = []
        for item in data['equipment'][:18]:
            label = f"{item.get('slot')}: " if item.get('slot') else ''
            enchant = f" +{item['enchant']}" if item.get('enchant') else ''
            lines.append(f"• {label}{item.get('name', 'Unknown item')}{enchant}")
        embed.add_field(name=f"Equipment ({len(data['equipment'])})", value='\n'.join(lines)[:1024], inline=False)
    elif data.get('equipment_status') == 'unavailable':
        embed.add_field(name='Equipment', value='Equipment data is temporarily unavailable.', inline=False)
    if source_text:
        embed.set_footer(text=source_text[:2048])
    elif character.get('last_success'):
        try:
            updated = datetime.fromisoformat(character['last_success']).astimezone().strftime('%b %d, %Y %I:%M %p %Z')
        except (ValueError, TypeError):
            updated = 'recently'
        embed.set_footer(text=f'AION 2 public character data · Updated {updated}')
    else:
        embed.set_footer(text='Member-entered character details · Not imported yet')
    if data.get('image_url'):
        embed.set_thumbnail(url=data['image_url'])
    return embed


def region_label(region):
    return next((choice.name for choice in AION_REGIONS if choice.value == region), region.upper())


class UnlinkConfirmView(discord.ui.View):
    def __init__(self, cog, user_id, link_id, name):
        super().__init__(timeout=45)
        self.cog, self.user_id, self.link_id, self.name = cog, user_id, link_id, name

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Only the member who requested this unlink can confirm it.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Unlink character', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        try:
            await self.cog.repository.change_link(self.user_id, self.link_id, delete=True)
            await interaction.response.edit_message(content=f'Unlinked **{self.name}** from your company profile.', embed=None, view=None)
        except Missing:
            await interaction.response.edit_message(content='That character is no longer linked to your profile.', embed=None, view=None)
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(content='Character kept on your profile.', embed=None, view=None)
        self.stop()


class MemberDashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.url = os.getenv('DASHBOARD_URL', '').rstrip('/') or None
        if self.url:
            parsed = urlsplit(self.url)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username is not None:
                raise ValueError('DASHBOARD_URL must be a web origin')
            if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1'):
                raise ValueError('Hosted dashboard links require HTTPS')
        self.guild_id = int(os.getenv('DASHBOARD_GUILD_ID') or os.environ['DISCORD_GUILD_ID'])
        self.visible = set(filter(None, os.getenv('DASHBOARD_VISIBLE_ROLE_IDS', '').replace(' ', '').split(',')))
        self.pool = None
        self.repository = None
        self.http = None
        self.aion = None
        self.search_adapters = {}

    async def cog_load(self):
        # Own pool: roster synchronization never initializes or mutates economy tables.
        import asyncpg
        import json
        async def init(conn):
            await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
        self.pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=2, init=init)
        if not await self.pool.fetchval("SELECT to_regclass('member_profiles')"):
            await self.pool.close()
            self.pool = None
            raise RuntimeError('Apply dashboard migrations before enabling the dashboard cog')
        self.repository = Repository(self.pool, self.guild_id)
        self.http = aiohttp.ClientSession(headers={'User-Agent': 'CompanyRoster/1.0'})
        self.aion = AionAdapter(self.http)
        # Character search spans independent regional endpoints. Keep one adapter
        # per region so their one-request-per-second pacing does not serialize
        # the cross-region autocomplete into a Discord interaction timeout.
        self.search_adapters = {choice.value: AionAdapter(self.http) for choice in AION_REGIONS}
        if self.url:
            self.sync_roster.start()

    async def cog_unload(self):
        self.sync_roster.cancel()
        if self.http:
            await self.http.close()
        if self.pool:
            await self.pool.close()

    async def save_member(self, member):
        if member.bot or member.guild.id != self.guild_id:
            return
        roles = [{'id': str(r.id), 'name': r.name} for r in member.roles if str(r.id) in self.visible]
        await self.pool.execute('''INSERT INTO member_profiles(guild_id,user_id,display_name,avatar_url,roles)
            VALUES($1,$2,$3,$4,$5) ON CONFLICT(guild_id,user_id) DO UPDATE SET display_name=excluded.display_name,
            avatar_url=excluded.avatar_url,roles=excluded.roles,active=true,updated_at=now()''',
                                self.guild_id, member.id, member.display_name, str(member.display_avatar.url), roles)

    @tasks.loop(minutes=15)
    async def sync_roster(self):
        try:
            guild = self.bot.get_guild(self.guild_id)
            if not guild:
                return
            # Complete member inventory is required before marking anyone inactive.
            members = await guild.chunk(cache=True)
            humans = [m for m in members if not m.bot]
            for member in humans:
                await self.save_member(member)
            await self.pool.execute('UPDATE member_profiles SET active=false WHERE guild_id=$1 AND NOT(user_id=ANY($2::bigint[]))',
                                    self.guild_id, [m.id for m in humans])
        except Exception:
            log.exception('Company roster sync failed; previous roster retained')

    @sync_roster.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if self.url:
            await self.save_member(member)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if self.url:
            await self.save_member(after)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if self.url and member.guild.id == self.guild_id:
            await self.pool.execute('UPDATE member_profiles SET active=false WHERE guild_id=$1 AND user_id=$2', self.guild_id, member.id)

    @app_commands.command(name='profile', description='Open your company member dashboard profile')
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('The company dashboard is available in the company server.', ephemeral=True)
            return
        if not self.url:
            await interaction.response.send_message('The AION 2 character commands are available, but the web dashboard is not configured.', ephemeral=True)
            return
        target = member or interaction.user
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label='Open member profile', url=f'{self.url}/#member/{target.id}'))
        await interaction.response.send_message('Sign in with Discord to view this company profile.', view=view, ephemeral=True)

    @app_commands.command(name='link-character', description='Link an AION 2 character to your company profile')
    @app_commands.guild_only()
    async def link_character(self, interaction: discord.Interaction, character_name: app_commands.Range[str, 1, 100],
                             make_main: bool = False):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Character linking is available in the company server.', ephemeral=True)
            return
        # The visible name field searches all regions. Its selected value is a
        # region/server/character reference, never an arbitrary submitted name.
        try:
            selected_region, selected_server, character_id = character_name.split('|', 2)
            selected_server = int(selected_server)
            from src.dashboard.aion import identity
            selected_region, selected_server, character_id = identity(selected_region, selected_server, character_id)
        except (ValueError, TypeError):
            await interaction.response.send_message('Select a character from the search suggestions.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.link_selected(interaction, {'region': selected_region, 'server_id': selected_server,
                                                   'character_id': character_id}, make_main, followup=True)
        except AionError as error:
            await interaction.followup.send(self.aion_error(error), ephemeral=True)
        except Exception:
            log.exception('AION 2 character search failed')
            await interaction.followup.send('AION 2 character search is temporarily unavailable. Please try again.', ephemeral=True)

    @link_character.autocomplete('character_name')
    async def character_autocomplete(self, interaction: discord.Interaction, current: str):
        if len(current.strip()) < 3:
            return []
        async def search_region(region):
            races = (1, 2) if region in ('kr', 'tw') else (1,)
            results = await asyncio.gather(
                *(self.search_adapters[region].search(region, current.strip(), race=race) for race in races),
                return_exceptions=True,
            )
            hits = []
            for result in results:
                if isinstance(result, Exception):
                    if not isinstance(result, AionError):
                        log.warning('AION 2 autocomplete failed for region %s (%s)', region, type(result).__name__)
                    continue
                hits.extend(result)
            return hits

        tasks = [asyncio.create_task(search_region(choice.value)) for choice in AION_REGIONS]
        done, pending = await asyncio.wait(tasks, timeout=2.4)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        hits = []
        for task in done:
            try:
                hits.extend(task.result())
            except Exception:
                log.exception('AION 2 cross-region autocomplete failed')

        # Prefer exact names, retaining upstream relevance within each group.
        hits.sort(key=lambda hit: (hit['name'].casefold() != current.strip().casefold(),
                                   next((i for i, c in enumerate(AION_REGIONS) if c.value == hit['region']), 99)))
        choices = []
        for hit in hits:
            value = f"{hit['region']}|{hit['server_id']}|{hit['character_id']}"
            if len(value) > 100:
                continue
            label = (f"{hit['region'].upper()} · {hit['name']} · "
                     f"{hit.get('server_name') or hit['server_id']} · Lv {hit.get('level') or '—'}")
            choices.append(app_commands.Choice(name=label[:100], value=value))
        return choices[:25]

    async def link_selected(self, interaction, hit, make_main, *, followup=False):
        try:
            data = await self.aion.character(hit['region'], hit['server_id'], hit['character_id'])
            member = interaction.user
            await self.save_member(member)
            link_id = await self.repository.link(member.id, hit['region'], hit['server_id'], hit['character_id'],
                                                data, 'imported', make_main)
            profile = await self.repository.profile(member.id)
            character = next(item for item in profile['characters'] if item['id'] == link_id)
            message = f"Linked **{data['name']}** on **{data.get('server_name') or hit['server_name']}** to your company profile."
            if not character['confirmed_at']:
                message += ' The link is self-reported until an officer confirms it.'
            sender = interaction.followup.send if followup or interaction.response.is_done() else interaction.response.send_message
            await sender(message, embed=character_embed(character), ephemeral=True)
        except Conflict as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except AionError as error:
            await interaction.followup.send(self.aion_error(error), ephemeral=True)
        except Exception:
            log.exception('AION 2 character import failed')
            await interaction.followup.send('I could not import that character right now. Please try again.', ephemeral=True)

    @staticmethod
    def aion_error(error):
        if error.kind == 'not_found':
            return 'AION 2 could not find that character on the selected server.'
        if error.kind == 'throttled':
            return 'AION 2 is limiting lookups right now. Please try again in a few minutes.'
        return 'AION 2 profile data is temporarily unavailable. Please try again shortly.'

    async def linked_choices(self, interaction, current):
        if interaction.guild_id != self.guild_id:
            return []
        try:
            profile = await self.repository.profile(interaction.user.id)
        except Missing:
            return []
        needle = current.casefold().strip()
        result = []
        for item in profile['characters']:
            data = item['data']
            label = f"{data.get('name', 'Character')} · {data.get('server_name') or item['region'].upper()}"
            if not needle or needle in label.casefold():
                result.append(app_commands.Choice(name=label[:100], value=item['id']))
        return result[:25]

    @app_commands.command(name='my-characters', description='View your linked AION 2 characters and their stats')
    @app_commands.guild_only()
    async def my_characters(self, interaction: discord.Interaction):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Character profiles are available in the company server.', ephemeral=True)
            return
        try:
            profile = await self.repository.profile(interaction.user.id)
        except Missing:
            await interaction.response.send_message('You do not have a company profile yet. Try `/link-character` first.', ephemeral=True)
            return
        if not profile['characters']:
            await interaction.response.send_message('You have no linked AION 2 characters. Use `/link-character` to search for yours.', ephemeral=True)
            return
        lines = []
        for item in profile['characters']:
            data = item['data']
            marker = '⭐ ' if item['is_main'] else ''
            stats = [f"Lv. {data['level']}" if data.get('level') is not None else None,
                     f"{data['combat_power']:,} CP" if data.get('combat_power') is not None else None]
            details = ' · '.join([x for x in [data.get('class_name'), data.get('server_name') or item['region'].upper(), *stats] if x])
            lines.append(f"{marker}**{discord.utils.escape_markdown(data.get('name') or 'Character')}** — {details or 'Stats unavailable'}")
        display_name = getattr(interaction.user, 'display_name', interaction.user.name)
        embed = discord.Embed(title=f"{display_name}'s AION 2 characters", description='\n'.join(lines)[:4000],
                              color=discord.Color.from_rgb(190, 222, 153))
        embed.set_footer(text='⭐ marks your main · Use /aion-stats for equipment and detailed stats')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='aion-stats', description='View detailed stats for one of your linked characters')
    @app_commands.guild_only()
    async def aion_stats(self, interaction: discord.Interaction, character: str | None = None):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Character profiles are available in the company server.', ephemeral=True)
            return
        try:
            profile = await self.repository.profile(interaction.user.id)
        except Missing:
            await interaction.response.send_message('You do not have a company profile yet. Try `/link-character` first.', ephemeral=True)
            return
        if not profile['characters']:
            await interaction.response.send_message('You have no linked AION 2 characters. Use `/link-character` to search for yours.', ephemeral=True)
            return
        selected = next((item for item in profile['characters'] if item['id'] == character), None) if character else next((item for item in profile['characters'] if item['is_main']), profile['characters'][0])
        if not selected:
            await interaction.response.send_message('That character is not linked to your profile. Pick one from the autocomplete list.', ephemeral=True)
            return
        await interaction.response.send_message(embed=character_embed(selected), ephemeral=True)

    @aion_stats.autocomplete('character')
    async def aion_stats_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.linked_choices(interaction, current)

    @app_commands.command(name='set-main', description='Choose your main AION 2 character')
    @app_commands.guild_only()
    async def set_main(self, interaction: discord.Interaction, character: str):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Character profiles are available in the company server.', ephemeral=True)
            return
        try:
            await self.repository.change_link(interaction.user.id, character)
            profile = await self.repository.profile(interaction.user.id)
            selected = next(item for item in profile['characters'] if item['id'] == character)
            await interaction.response.send_message(f"**{selected['data'].get('name', 'Character')}** is now your main.", embed=character_embed(selected), ephemeral=True)
        except Missing:
            await interaction.response.send_message('Choose one of your linked characters from the autocomplete list.', ephemeral=True)

    @set_main.autocomplete('character')
    async def set_main_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.linked_choices(interaction, current)

    @app_commands.command(name='unlink-character', description='Remove one of your linked characters')
    @app_commands.guild_only()
    async def unlink_character(self, interaction: discord.Interaction, character: str):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Character profiles are available in the company server.', ephemeral=True)
            return
        try:
            profile = await self.repository.profile(interaction.user.id)
            selected = next(item for item in profile['characters'] if item['id'] == character)
        except (Missing, StopIteration):
            await interaction.response.send_message('Choose one of your linked characters from the autocomplete list.', ephemeral=True)
            return
        view = UnlinkConfirmView(self, interaction.user.id, character, selected['data'].get('name', 'this character'))
        await interaction.response.send_message(f"Unlink **{selected['data'].get('name', 'this character')}** from your company profile?", view=view, ephemeral=True)

    @unlink_character.autocomplete('character')
    async def unlink_character_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.linked_choices(interaction, current)

    @app_commands.command(name='refresh-character', description='Refresh one of your AION 2 character profiles')
    @app_commands.guild_only()
    async def refresh_character(self, interaction: discord.Interaction, character: str):
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Character profiles are available in the company server.', ephemeral=True)
            return
        try:
            profile = await self.repository.profile(interaction.user.id)
            selected = next(item for item in profile['characters'] if item['id'] == character)
        except (Missing, StopIteration):
            await interaction.response.send_message('Choose one of your linked characters from the autocomplete list.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        char_id = int(selected['character_id'])
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow('SELECT last_attempt FROM aion_characters WHERE id=$1 FOR UPDATE', char_id)
                if row and row['last_attempt'] and (datetime.now(row['last_attempt'].tzinfo)-row['last_attempt']).total_seconds() < 600:
                    await interaction.followup.send('This character was refreshed recently. Please wait a few minutes and try again.', ephemeral=True)
                    return
                await conn.execute('UPDATE aion_characters SET last_attempt=now(),refresh_status=\'refreshing\' WHERE id=$1', char_id)
        try:
            data = await self.aion.character(selected['region'], selected['server_id'], selected['upstream_id'])
            await self.repository.link(interaction.user.id, selected['region'], selected['server_id'], selected['upstream_id'], data, 'imported', selected['is_main'])
            fresh = await self.repository.profile(interaction.user.id)
            selected = next(item for item in fresh['characters'] if item['id'] == character)
            await interaction.followup.send('AION 2 stats refreshed.', embed=character_embed(selected), ephemeral=True)
        except AionError as error:
            await self.pool.execute('UPDATE aion_characters SET refresh_status=$2 WHERE id=$1', char_id, error.kind)
            await interaction.followup.send(self.aion_error(error), ephemeral=True)
        except Exception:
            await self.pool.execute("UPDATE aion_characters SET refresh_status='unavailable' WHERE id=$1", char_id)
            log.exception('AION 2 character refresh failed')
            await interaction.followup.send('AION 2 refresh failed. Your last saved profile is still available.', ephemeral=True)

    @refresh_character.autocomplete('character')
    async def refresh_character_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.linked_choices(interaction, current)


async def setup(bot):
    await bot.add_cog(MemberDashboard(bot))
