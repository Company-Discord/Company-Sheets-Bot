import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './styles.css';

type Me = {user_id:string;display_name:string;avatar_url:string|null;is_officer:boolean;csrf:string;imports_enabled:boolean};
type Summary = {name:string;class_name:string|null;server_name:string|null;region:string;confirmed:boolean};
type Member = {user_id:string;display_name:string;avatar_url:string|null;roles:{id:string;name:string}[];main_character:Summary|null;character_count:number};
type CharacterData = {name:string;class_name?:string;server_name?:string;level?:number;combat_power?:number;item_level?:number;profile_url:string;equipment?:{name:string;slot:string;enchant:number|null}[];equipment_status?:string};
type Character = {id:string;character_id:string;region:string;is_main:boolean;confirmed_at:string|null;source:string;last_success:string|null;refresh_status:string;refresh_pending:boolean;data:CharacterData};
type Profile = Member & {characters:Character[];preferences:string;availability:string;balances:null|{cash:string;bank:string;source:string}};
type Hit = {region:string;server_id:number;character_id:string;name:string;server_name:string;level:number};
const regions:Record<string,string> = {nae:'NA East',naw:'NA West',eu:'Europe',sa:'South America',asia:'Asia',kr:'Korea',tw:'Taiwan'};
let csrf = '';
async function api<T>(path:string, method='GET', body?:unknown):Promise<T> {
  const response = await fetch(path, {method, credentials:'same-origin', headers:{...(body ? {'Content-Type':'application/json'} : {}),...(method !== 'GET' ? {'X-CSRF-Token':csrf} : {})},body:body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check your details and try again.');
  return data;
}
const money = (value:string) => BigInt(value).toLocaleString();
const stamp = (value:string|null) => value ? new Date(value).toLocaleString() : 'Not imported yet';

function Avatar({member}:{member:{display_name:string;avatar_url:string|null}}) {
  return member.avatar_url ? <img className="avatar" src={member.avatar_url} alt=""/> : <span className="avatar initials" aria-hidden="true">{member.display_name.slice(0,2).toUpperCase()}</span>;
}

function App() {
  const [me,setMe] = useState<Me|null>(null), [ready,setReady] = useState(false), [error,setError] = useState('');
  const [view,setView] = useState(location.hash.startsWith('#member/') ? location.hash.slice(8) : 'roster');
  useEffect(() => {api<Me>('/api/v1/me').then(user => {csrf=user.csrf;setMe(user);const target=sessionStorage.getItem('company-profile-target');if(target){sessionStorage.removeItem('company-profile-target');if(/^#member\/[1-9][0-9]{0,18}$/.test(target))location.hash=target}}).catch(e=>setError(e.message)).finally(()=>setReady(true));
    const change=()=>setView(location.hash.startsWith('#member/') ? location.hash.slice(8) : 'roster');
    addEventListener('hashchange',change);return()=>removeEventListener('hashchange',change);
  },[]);
  return <div className="shell">
    <aside><a className="brand" href="#"><span className="brand-mark">C</span><span>COMPANY<span className="brand-sub">MEMBER HEADQUARTERS</span></span></a>
      <div className="sidebar-label">YOUR COMPANY</div><nav><a className={view==='roster'?'active':''} href="#">▦ <span>Member roster</span></a>{me && <a className={view===me.user_id?'active':''} href={`#member/${me.user_id}`}>◈ <span>My profile</span></a>}</nav>
      <div className="sidebar-note"><span className="live-dot"/> AION 2 · Company roster<p>Your people. Your characters.<br/>One place to connect.</p></div>
      <div className="sidebar-footer">COMPANY SHEETS BOT <span>01</span></div>
    </aside>
    <main><header><span className="breadcrumb">Company HQ <span>/</span> {view==='roster'?'Members':'Profile'}</span>{me && <div className="account"><span>{me.display_name}</span><button className="text-button" onClick={()=>api('/auth/logout','POST').then(()=>location.reload()).catch(e=>setError(e.message))}>Sign out</button></div>}</header>
      {!ready ? <div className="empty">Opening your company…</div> : !me ? <section className="welcome"><span className="eyebrow">THE COMPANY, CONNECTED</span><h1>Every member.<br/>Every adventure.</h1><p>Find your company members, connect your AION 2 characters, and keep your profile in one place.</p><a className="button primary" href="/auth/discord" onClick={()=>{if(location.hash.startsWith("#member/"))sessionStorage.setItem("company-profile-target",location.hash)}}>Continue with Discord <span>↗</span></a><p className="small muted">Access is limited to members of your company Discord server.</p>{error && <p className="notice" role="status">{error}</p>}</section> : view==='roster' ? <Roster/> : <MemberProfile key={view} userId={view} me={me}/>}
    </main></div>;
}

function Roster() {
  const [q,setQ]=useState(''),[region,setRegion]=useState(''),[cls,setCls]=useState(''),[server,setServer]=useState(''),[kind,setKind]=useState('');
  const [offset,setOffset]=useState(0),[data,setData]=useState<{items:Member[];total:number}>({items:[],total:0});
  const [filters,setFilters]=useState<{classes:string[];servers:string[]}>({classes:[],servers:[]});
  const [error,setError]=useState(''),[loading,setLoading]=useState(true);
  useEffect(()=>{api<typeof filters>('/api/v1/filters').then(setFilters).catch(e=>setError(e.message))},[]);
  useEffect(()=>{let live=true;setLoading(true);const timer=setTimeout(()=>{
    const params=new URLSearchParams({q,region,class_name:cls,server,kind,offset:String(offset)});
    api<typeof data>('/api/v1/members?'+params).then(d=>{if(live){setData(d);setError('')}}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)});
  },250);return()=>{live=false;clearTimeout(timer)}},[q,region,cls,server,kind,offset]);
  return <section><div className="page-title"><div><span className="eyebrow">PEOPLE BEHIND THE CHARACTERS</span><h1>Member roster<span className="title-dot">.</span></h1><p className="muted">Find your people. See who they bring to the fight.</p></div><span className="pill">DISCORD CONNECTED</span></div>
    <div className="stats"><div><span>Matching members</span><strong>{data.total.toString().padStart(2,'0')}</strong></div><div><span>Character classes</span><strong>{filters.classes.length.toString().padStart(2,'0')}</strong></div><div><span>Servers represented</span><strong>{filters.servers.length.toString().padStart(2,'0')}</strong></div><div className="stats-caption"><span>Built for the company</span><p>Discord identities.<br/>AION 2 adventures.</p></div></div>
    <div className="section-heading"><h2>The roster</h2><span className="muted small">Main characters & company members</span></div>
    <div className="filters"><label className="search"><span>⌕</span><input aria-label="Search members or characters" placeholder="Search member or character…" value={q} onChange={e=>{setQ(e.target.value);setOffset(0)}}/></label>
      <select aria-label="Filter region" value={region} onChange={e=>{setRegion(e.target.value);setOffset(0)}}><option value="">All regions</option>{Object.entries(regions).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select>
      <select aria-label="Filter class" value={cls} onChange={e=>{setCls(e.target.value);setOffset(0)}}><option value="">All classes</option>{filters.classes.map(v=><option key={v}>{v}</option>)}</select>
      <select aria-label="Filter server" value={server} onChange={e=>{setServer(e.target.value);setOffset(0)}}><option value="">All servers</option>{filters.servers.map(v=><option key={v}>{v}</option>)}</select>
      <select aria-label="Filter character type" value={kind} onChange={e=>{setKind(e.target.value);setOffset(0)}}><option value="">All characters</option><option value="main">Mains</option><option value="alternate">Alternates</option></select></div>
    {error && <p className="notice" role="alert">{error}</p>}
    {loading ? <div className="empty" role="status">Loading members…</div> : data.items.length===0 ? <div className="empty"><h3>No members found</h3><p>Try another filter, or open My profile to link your first character.</p></div> : <div className="roster-grid">{data.items.map(member=><a className="member-card" key={member.user_id} href={`#member/${member.user_id}`}>
      <div className="member-top"><Avatar member={member}/><span className="card-arrow">↗</span></div><h3>{member.display_name}</h3><div className="roles">{member.roles.length ? member.roles.map(r=><span key={r.id}>{r.name}</span>) : <span>Company member</span>}</div>
      <div className="character-summary">{member.main_character ? <><span className="small muted">MAIN CHARACTER</span><strong>{member.main_character.name}</strong><span>{member.main_character.class_name || 'Class unavailable'} <span className="muted">/</span> {member.main_character.server_name || regions[member.main_character.region]}</span><div className="card-bottom"><span className={member.main_character.confirmed?'confirmed':'muted'}>{member.main_character.confirmed?'✓ Officer confirmed':'Self-reported link'}</span><span>{member.character_count} linked</span></div></> : <><span className="small muted">AION 2 CHARACTERS</span><strong className="muted">Not linked yet</strong><p className="small muted">Their next adventure starts here.</p></>}</div>
    </a>)}</div>}
    <div className="pagination"><span className="muted small">{data.total?`${offset+1}–${Math.min(offset+24,data.total)} of ${data.total} members`:'0 members'}</span><div><button disabled={offset===0||loading} onClick={()=>setOffset(Math.max(0,offset-24))}>← Previous</button><button disabled={offset+24>=data.total||loading} onClick={()=>setOffset(offset+24)}>Next →</button></div></div>
  </section>;
}

function MemberProfile({userId,me}:{userId:string;me:Me}) {
  const [profile,setProfile]=useState<Profile|null>(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[linking,setLinking]=useState(false);
  const [preferences,setPreferences]=useState(''),[availability,setAvailability]=useState(''),[removing,setRemoving]=useState<string|null>(null),[reassign,setReassign]=useState('');
  const own=userId===me.user_id;
  const load=async()=>{const p=await api<Profile>('/api/v1/members/'+encodeURIComponent(userId));setProfile(p);setPreferences(p.preferences);setAvailability(p.availability)};
  useEffect(()=>{load().catch(e=>setError(e.message))},[userId]);
  const act=async(path:string,method='POST',body?:unknown)=>{setBusy(true);setError('');setMessage('');try{await api(path,method,body);await load();setMessage('Saved.');setRemoving(null)}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
  return <section><a className="back-link" href="#">← Back to roster</a>{error&&<p className="notice" role="alert">{error}</p>}{message&&<p className="success" role="status">{message}</p>}
    {!profile ? <div className="empty">{error?'Profile unavailable':'Loading profile…'}</div> : <><div className="profile-heading"><Avatar member={profile}/><div><span className="eyebrow">COMPANY MEMBER</span><h1>{profile.display_name}</h1><div className="roles">{profile.roles.map(r=><span key={r.id}>{r.name}</span>)}</div></div>{own&&<button className="primary" onClick={()=>setLinking(!linking)}>{linking?'Close linking':'＋ Link character'}</button>}</div>
      {linking&&own&&<LinkForm me={me} onLinked={async()=>{setLinking(false);await load()}}/>}
      <div className="profile-columns"><div><div className="section-heading"><h2>AION 2 characters</h2><span className="muted small">{profile.characters.length} linked</span></div>
        {!profile.characters.length&&<div className="empty"><h3>No characters linked</h3><p>{own?'Link your main character to introduce yourself to the company.':'This member has not linked a character yet.'}</p></div>}
        {profile.characters.map(c=><article className="character-card" key={c.id}><div className="section-heading"><div><span className="eyebrow">{c.is_main?'MAIN CHARACTER':'ALTERNATE'} · {regions[c.region]}</span><h2>{c.data.name}</h2><p className="muted">{c.data.class_name||'Class unavailable'} · {c.data.server_name||'Server unavailable'}</p></div><span className={c.confirmed_at?'badge confirmed':'badge'}>{c.confirmed_at?'✓ Officer confirmed':'Self-reported link'}</span></div>
          <div className="character-numbers"><div><span>Level</span><strong>{c.data.level??'—'}</strong></div><div><span>Combat power</span><strong>{c.data.combat_power?.toLocaleString()??'—'}</strong></div><div><span>Item level</span><strong>{c.data.item_level??'—'}</strong></div></div>
          <p className="small muted">{c.source==='manual'?'Member-entered details':'AION 2 public character data'} · {stamp(c.last_success)}</p>
          {c.source==='imported'&&(c.refresh_status!=='available'||(c.last_success&&Date.now()-Date.parse(c.last_success)>21600000))&&<p className="notice small">Showing the last saved profile. A fresh update is currently unavailable.</p>}
          {!!c.data.equipment?.length&&<details><summary>Equipment · {c.data.equipment.length} items</summary><ul className="equipment">{c.data.equipment.map((i,index)=><li key={index}><span>{i.slot||'Equipment'}</span><strong>{i.name}{i.enchant ? ` +${i.enchant}`:''}</strong></li>)}</ul></details>}
          {c.data.equipment_status==='unavailable'&&<p className="small muted">Equipment is currently unavailable.</p>}
          <div className="actions"><a className="button" href={c.data.profile_url} target="_blank" rel="noopener noreferrer">Official profile ↗</a>{own&&<><button disabled={busy||c.is_main} onClick={()=>act('/api/v1/me/characters/'+c.id,'PATCH')}>Set as main</button>{me.imports_enabled&&<button disabled={busy||c.refresh_pending} onClick={()=>act('/api/v1/characters/'+c.character_id+'/refresh')}>{c.refresh_pending?'Refresh queued':'Refresh'}</button>}<button className="text-button danger" onClick={()=>setRemoving(c.id)}>Unlink</button></>}{me.is_officer&&!c.confirmed_at&&<button disabled={busy} onClick={()=>act('/api/v1/character-links/'+c.id+'/confirm')}>Confirm link</button>}</div>
          {removing===c.id&&<div className="notice">Unlink {c.data.name} from your profile? <button disabled={busy} onClick={()=>act('/api/v1/me/characters/'+c.id,'DELETE')}>Unlink character</button> <button onClick={()=>setRemoving(null)}>Keep character</button></div>}
          {me.is_officer&&<details><summary>Officer tools</summary><p className="small muted">Confirmation records officer approval of this link, not NCSOFT account ownership.</p><label>Reassign to Discord member ID<input value={reassign} onChange={e=>setReassign(e.target.value)} placeholder="Member's Discord ID"/></label><button disabled={busy||!reassign.match(/^[1-9][0-9]{0,18}$/)} onClick={()=>act('/api/v1/character-links/'+c.id+'/reassign','POST',{user_id:reassign})}>Reassign and confirm</button></details>}
        </article>)}
      </div><div><article className="panel"><span className="eyebrow">IN THE COMPANY</span><h2>Play preferences</h2>{own?<form onSubmit={e=>{e.preventDefault();act('/api/v1/me/preferences','PATCH',{preferences,availability})}}><label>Activities<textarea maxLength={500} value={preferences} onChange={e=>setPreferences(e.target.value)} placeholder="Dungeons, PvP, helping new members…"/></label><label>Usually available<textarea maxLength={500} value={availability} onChange={e=>setAvailability(e.target.value)} placeholder="Weeknights 8–11 PM Eastern"/></label><button disabled={busy} type="submit">Save preferences</button></form>:<><p>{profile.preferences||'No activities shared yet.'}</p><span className="small muted">USUALLY AVAILABLE</span><p>{profile.availability||'Not shared yet.'}</p></>}</article>
        {profile.balances&&<article className="panel"><span className="eyebrow">LOCAL BOT ECONOMY</span><h2>Member balance</h2><dl className="balance"><div><dt>Cash</dt><dd>{money(profile.balances.cash)}</dd></div><div><dt>Bank</dt><dd>{money(profile.balances.bank)}</dd></div></dl><p className="small muted">Visible to the member and company officers. Engauge currency is separate.</p></article>}
        <div className="profile-note"><span className="live-dot"/> Connected through Discord<p>Character links are self-reported until an officer confirms the association.</p></div>
      </div></div></>}
  </section>;
}

function LinkForm({me,onLinked}:{me:Me;onLinked:()=>Promise<void>}) {
  const [region,setRegion]=useState('nae'),[q,setQ]=useState(''),[race,setRace]=useState('1'),[server,setServer]=useState('');
  const [servers,setServers]=useState<{id:number;name:string}[]>([]),[hits,setHits]=useState<Hit[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [url,setUrl]=useState(''),[name,setName]=useState(''),[cls,setCls]=useState(''),[serverName,setServerName]=useState('');
  useEffect(()=>{setServers([]);setHits([]);setServer('');if(me.imports_enabled)api<typeof servers>('/api/v1/aion/servers?region='+region).then(setServers).catch(e=>setError(e.message))},[region]);
  const submit=async(body:unknown)=>{setBusy(true);setError('');try{await api('/api/v1/me/characters','POST',body);await onLinked()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
  return <article className="panel link-panel"><div className="section-heading"><h2>Link an AION 2 character</h2><span className="badge">MAIN OR ALTERNATE</span></div><p className="muted">Choose the region where your character plays. Your first linked character becomes your main.</p>
    <label>Region<select value={region} onChange={e=>setRegion(e.target.value)}>{Object.entries(regions).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
    {me.imports_enabled&&<form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{const params=new URLSearchParams({region,q,race});if(server)params.set('server_id',server);setHits(await api<Hit[]>('/api/v1/aion/search?'+params))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>
      <div className="form-row"><label>Character name<input minLength={2} maxLength={50} required value={q} onChange={e=>setQ(e.target.value)}/></label><label>Server<select value={server} onChange={e=>setServer(e.target.value)}><option value="">All servers</option>{servers.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>{['kr','tw'].includes(region)&&<label>Faction<select value={race} onChange={e=>setRace(e.target.value)}><option value="1">Elyos</option><option value="2">Asmodian</option></select></label>}<button disabled={busy} type="submit">Search</button></div>
      <ul className="search-results">{hits.map(h=><li key={h.server_id+h.character_id}><span><strong>{h.name}</strong> · {h.server_name} · Level {h.level??'—'}</span><button type="button" disabled={busy} onClick={()=>submit({...h,is_main:false})}>Link character</button></li>)}</ul></form>}
    <form onSubmit={e=>{e.preventDefault();submit({region,profile_url:url,name,class_name:cls,server_name:serverName})}}><h3>{me.imports_enabled?'Or paste an official profile':'Link your official profile'}</h3><label>Official AION 2 character URL<input type="url" required maxLength={2000} value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://aion2.plaync.com/en-us/characters/detail?…"/></label>
      {!me.imports_enabled&&<><p className="small muted">Automatic imports are not enabled yet. These details will be marked as member-entered.</p><div className="form-row"><label>Character name<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label><label>Class<input maxLength={60} value={cls} onChange={e=>setCls(e.target.value)}/></label><label>Server name<input maxLength={100} value={serverName} onChange={e=>setServerName(e.target.value)}/></label></div></>}
      <button className="primary" disabled={busy} type="submit">{busy?'Linking…':'Link character'}</button></form>{error&&<p className="notice" role="alert">{error}</p>}
  </article>;
}

createRoot(document.getElementById('root')!).render(<App/>);
