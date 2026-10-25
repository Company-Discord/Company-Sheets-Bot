**Proposal: a members-only “Company Roster” dashboard connecting each Discord member to their AION 2 characters and bot activity.**

Members could quickly see who plays which class, inspect character profiles, track progress, and find people for groups.

**What members would see**

| Feature | Details |
|---|---|
| Member directory | Discord avatar, display name, company role, main character, class, server |
| Member profile | Main and alternate characters, bot balances, activity summary, achievements |
| Character overview | Available public character information, official profile link, last refresh time |
| Progress tracking | Changes in available character stats collected after linking |
| Group availability | Preferred activities, usual play times, and “looking for group” status |

Example profile:

```text
Discord: Alex                       Company role: Officer
Main: CharacterName                 Server: Selected server
Class: Templar                      Character link: Officer confirmed

[AION 2 character] [Company activity] [Economy]

Preferred activities: Dungeons · PvP
Usually available: Weeknights, 8–11 PM Eastern
```

**Connecting Discord members**

Members sign in with Discord. The backend checks that they belong to your company server, then uses their Discord user ID as their dashboard identity.

We can connect that identity to your existing bot data using `guild_id + user_id`, showing balances and other recorded statistics. Company roles can come from Discord; members can edit their play times and activity preferences.

Add a `/profile` command that opens the member’s dashboard page and a `/link-character` command that starts character linking.

**Connecting AION 2 characters**

AION 2 currently has an official character search with region and server selection. That gives us an official profile destination for linked characters. [Official AION 2 character search](https://aion2.plaync.com/en-us/characters/index)

The linking flow would be:

1. Member selects their region and server, then supplies a character name or official profile link.
2. We save the character identifier where available, alongside region and server.
3. Member chooses whether it is their main or an alternate.
4. An officer confirms the association, or it remains marked “self-reported.”

**Discord sign-in proves the Discord identity; it doesn’t prove ownership of an AION character.** Officer confirmation is a simple first-release solution.

For automatic character information, we should first inspect and validate the public requests behind the official search. I haven’t established a documented developer API or supported authentication integration. Automatic imports should therefore be a separate integration milestone, with official profile links and member-entered details available from day one.

Once validated, a background worker could refresh supported fields periodically, cache the results, and preserve the last successful snapshot when the source is unavailable.

**How we would build it**

Keep your existing Python bot and PostgreSQL database. Add a small web API and dashboard frontend, with three new tables:

- `member_profiles`: preferences, availability, visibility.
- `linked_characters`: Discord member, character identity, main/alternate, confirmation status.
- `character_snapshots`: imported fields, source, collection time.

Keep local bot currency and Engauge currency clearly labeled. Activity charts will need additional collection where your current records don’t retain the necessary history.

**Recommended first release**

Build Discord sign-in, the searchable roster, member profiles, character links, officer confirmation, and existing bot balances.

Then add automatic character imports and progression charts after validating the AION data source. Group signup and class-based roster planning would be the next useful expansion.

This gives your company an immediately useful roster while creating a clear path toward the richer character dashboard you liked in Notmeter.