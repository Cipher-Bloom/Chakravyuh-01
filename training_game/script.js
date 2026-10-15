const AVATAR="data:image/jpeg;base64,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";
const ESCALATIONS=["The attacker moves deeper into the network.","Data exfiltration risk just went up.",
"The intrusion spreads to another system.","Leadership wants answers — this needs to move faster.",
"The Deceiver covers their tracks. You've lost the trail.","Customer trust takes another hit."];
const GOODLINES=["Good call. That door just closed on them.","Nice catch — that stopped it cold.",
"That was the right move.","Exactly the kind of call that contains a breach."];

// part: [situation, [options], correctIndex, explain, hint, flag]
const PHASES=[
{name:"First Alarm",theme:"Detection & Triage",intro:"It's 03:47. Alerts are flooding the SOC dashboard. Nishika pulls you in: 'Someone in Finance may have just opened the door for whoever is doing this. Walk me through it with me.'",seal:"Awareness Seal",badge:"Phishing Hunter",parts:[
["Priya from Finance forwards an email: 'Your account closes in 15 minutes unless you verify now.' Sender: admin@nexacorp-secure-login.com. It asks for her password and OTP. What do we tell her?",
["Click the link and verify quickly, before it closes","Send the OTP over so IT can confirm it's really them","Ignore the email and verify only through the official helpdesk","Reply to the sender asking them to prove who they are"],2,
"Urgency, a lookalike domain, and requests for a password or OTP are classic phishing signs. Always verify through a channel you already trust, never one the message itself provides.",
"Look closely at the sender's domain, not the display name.","FLAG{VERIFY_FIRST}"],
["Another employee forwards a text: 'Claim your reward now: http://payrewards.claim-bonus.info'. Do we let it through?",
["Approve it, reward links are harmless","Block it — unfamiliar, urgent domains are a phishing pattern","Forward it to more staff to see who else got it","Reply asking them to enter card details to verify"],1,
"Reward messages with urgency and unfamiliar domains are a common phishing pattern. Legitimate offers never need you to rush.",
"Read the actual domain carefully — is it a company you recognize?","FLAG{CHECK_THE_DOMAIN}"],
["Nishika's phone rings — someone claiming to be 'IT support' is asking her for a one-time password to 'fix an urgent issue.' What does she do?",
["Give them the OTP, it sounds urgent","Hang up and call IT back on the official number herself","Give half the OTP as a compromise","Ask them to call back later with the same request"],1,
"No legitimate IT team ever asks for your OTP over the phone. This is voice phishing (vishing), and it's happening in real time.",
"A real OTP should never leave the device or the login screen.","FLAG{NEVER_SHARE_OTP}"]]},
{name:"Stolen Keys",theme:"Identity & Access",intro:"Nishika frowns at her screen. 'There's a login from Mumbai on the marketing account — nobody on that team is traveling. We need to lock this down before they pivot anywhere else.'",seal:"Identity Seal",badge:"Password Guardian",parts:[
["We're forcing a reset on the compromised account. Which replacement password do we set?",
["password123","Tr0ub4dor&3","correcthorsebatterystaple-92!Zq","Summer2024"],2,
"Length combined with unpredictability beats short, pattern-based substitutions. A long, unique passphrase is far harder to crack.",
"Think about length, not just special characters.","FLAG{LENGTH_BEATS_TRICKS}"],
["An audit shows that account's password is reused on two other internal tools. What's the real risk?",
["Only the marketing account is at risk","The attacker can try that same password on the other tools too","Nothing, breaches only affect one account","The password gets stronger the more it's used"],1,
"Password reuse means a single breach can cascade into every account sharing that password — a technique called credential stuffing.",
"Think about what an attacker does with a leaked password.","FLAG{NEVER_REUSE_PASSWORDS}"],
["Nishika asks: should we finally enable MFA org-wide, even though some teams complained it's inconvenient?",
["No, passwords alone are enough","Yes — it adds a second layer beyond just a password","No, it's not worth the friction","Only after another breach happens"],1,
"MFA means a stolen password alone isn't enough to log in, which would have blocked this takeover before it started.",
"MFA stands for 'multi-factor' — more than one proof of identity.","FLAG{MFA_SAVES_ACCOUNTS}"]]},
{name:"Into the Network",theme:"Containment",intro:"Traffic logs are lighting up. 'They're moving laterally,' Nishika says. 'Every minute we don't contain this, they reach another system.'",seal:"Network Seal",badge:"Packet Detective",parts:[
["The internal admin panel is still served over http:// instead of https://. Do we flag this as a problem right now?",
["No, both are equally safe","Yes — unencrypted traffic here could be intercepted","No, http is actually the newer protocol","Only shopping sites need https"],1,
"HTTPS encrypts traffic between the browser and the server. Plain HTTP sends data, including logins, in readable form — exactly what an attacker on the network wants.",
"The 's' in https stands for something important.","FLAG{HTTPS_NOT_HTTP}"],
["A remote employee has been working from a cafe's open Wi-Fi with no password. What do we advise?",
["Keep working as normal, it's just Wi-Fi","Avoid sensitive logins there, or require a VPN","Share the Wi-Fi password with the whole team","Disable the laptop's firewall for faster speed"],1,
"Open Wi-Fi lets nearby attackers snoop on unencrypted traffic. Sensitive work should go through a VPN or wait for a trusted network.",
"Open networks have no password, which means no built-in encryption.","FLAG{AVOID_OPEN_WIFI}"],
["Logs show repeated connections on port 23 (Telnet) to a server that should only allow port 22 (SSH). Why does this matter?",
["Telnet is a newer, encrypted replacement for SSH","Telnet sends data, including passwords, in plain text","Port numbers don't affect security","Telnet is only used for gaming"],1,
"Telnet predates modern encryption and transmits everything, including credentials, unencrypted. That open port is likely how they're moving between servers.",
"One of these protocols is decades older and was never built with encryption.","FLAG{SSH_OVER_TELNET}"]]},
{name:"The Backdoor",theme:"Application Layer",intro:"'They found a way into the customer portal,' Nishika says, sharing her screen. 'This is how they're keeping access even after we lock accounts.'",seal:"Application Seal",badge:"Web Defender",parts:[
["The portal's login form accepted ' OR 1=1 -- as a username, with no real password, and let someone in. What does this reveal?",
["The site has excellent security","The site is vulnerable to SQL injection","The password field is optional by design","This is normal for all websites"],1,
"That input is a classic SQL injection payload. If it works, the site isn't properly validating or sanitizing user input — and that's the hole they walked through.",
"This input tries to trick a database query, not guess a password.","FLAG{SANITIZE_YOUR_INPUT}"],
["Customers report a login page that looks identical to NexaCorp's, but the URL is secure-nexacorp-login.net instead of nexacorp.com. What is this?",
["A mirror site for faster loading","A phishing page cloned to steal customer credentials","An official backup login page","A harmless browser quirk"],1,
"Attackers often clone a real site's design onto a lookalike domain to steal credentials. The design can be copied perfectly — the real domain can't.",
"Check the actual domain, not how familiar the page looks.","FLAG{DOMAIN_OVER_DESIGN}"],
["A support engineer notices any logged-in customer can view another customer's invoices just by changing an ID number in the URL. This is:",
["A helpful feature for support staff","A broken access control vulnerability","Normal database behavior","A caching optimization"],1,
"This is broken access control: the app never checks whether this specific user is allowed to see that specific data.",
"The problem is about permissions, not passwords.","FLAG{CHECK_ACCESS_CONTROL}"]]},
{name:"Containing the Fire",theme:"Recovery",intro:"'We know how they got in, and where they've been,' Nishika says. 'Now we close every door and bring NexaCorp back up safely.'",seal:"Defense Seal",badge:"Incident Commander",parts:[
["A laptop on the network is confirmed infected. What's the first move?",
["Keep it running and monitor quietly","Disconnect it from the network immediately and report it","Delete files on it to remove the malware yourself","Restart it repeatedly until it looks fine"],1,
"Isolating the device first stops the infection from spreading, and reporting it lets the response team investigate properly before anything is lost.",
"Containment comes before investigation.","FLAG{ISOLATE_FIRST}"],
["A well-meaning teammate suggests deleting the suspicious log files to 'tidy things up' before the report goes out. Do we let them?",
["Sure, logs just take up space","No — logs are the evidence we need to understand what happened","It doesn't matter, logs reset on their own","Deleting them will stop the attacker immediately"],1,
"Logs are critical evidence for reconstructing the attack and proving what was and wasn't affected. Deleting them destroys the ability to investigate.",
"Think about what investigators need after any incident.","FLAG{PRESERVE_EVIDENCE}"],
["Before restoring the customer portal from backup, what's essential to check?",
["That it's the most recent backup, whatever the date","That the backup predates the compromise and is verified clean","That it's stored on the same server that got hit","Nothing — any backup is safe to restore"],1,
"Restoring from an infected backup just reintroduces the problem. It must be verified clean and taken before the compromise began.",
"The most recent backup isn't always the safest one.","FLAG{VERIFY_BEFORE_RESTORE}"]]}
];

let S={};
function resetGame(){S={screen:'start',phase:0,part:0,integrity:5,score:0,attempts:0,flags:[],badges:[]};}
resetGame();
const el=document.getElementById('app');
const rnd=a=>a[Math.floor(Math.random()*a.length)];

function render(){
  if(S.screen==='start')return renderStart();
  if(S.screen==='phaseReset')return renderPhaseReset();
  if(S.screen==='phaseComplete')return renderPhaseComplete();
  if(S.screen==='victory')return renderVictory();
  renderGame();
}
function bar(){
  let pips='';for(let i=0;i<5;i++)pips+=`<span class="${i<S.integrity?'on':''}">🛡</span>`;
  return `<div class="topbar">
    <div class="stat">Phase <b>${S.phase+1}/5</b></div>
    <div class="pips">${pips}</div>
    <div class="stat">Score <b>${S.score}</b> · Flags <b>${S.flags.length}</b></div>
  </div>`;
}
function map(){
  return `<div class="map">${PHASES.map((r,i)=>{
    const cls=i<S.phase?'done':i===S.phase?'current':'locked';
    const icon=i<S.phase?'✓':i===S.phase?'●':'🔒';
    return `<div class="node ${cls}"><div class="dot">${icon}</div><small>${r.name}</small></div>`;
  }).join('')}</div>`;
}
function renderStart(){
  el.innerHTML=`<div class="hero">
    <div class="spiral">🕸️</div>
    <h1>Chakarvyuh</h1>
    <p class="tag">THE NEXACORP INCIDENT</p>
    <p class="story">03:47 AM. Alerts are flooding NexaCorp's SOC dashboard. Nishika, the on-call SOC Lead, pulls you into the response: "We're under attack — I need you thinking clearly through every call." An intruder known only as <b>The Deceiver</b> has built a trap of five layers through the company's systems. Every choice you make either closes a door on them, or opens one wider.</p>
    <p class="brief">Five phases, three decisions each. Nishika will brief you before every call — answer wrong and the breach escalates. Run out of integrity in a phase, and you regroup to try it again.</p>
    <button class="btn" id="go">Join the Response</button>
  </div>`;
  document.getElementById('go').onclick=()=>{S.screen='game';S.attempts=0;render();};
}
function renderGame(){
  const r=PHASES[S.phase],p=r.parts[S.part];
  const showIntro=S.part===0&&S.attempts===0;
  el.innerHTML=bar()+map()+`<div class="card">
    <div class="phaselabel">${r.theme} · Decision ${S.part+1}/3</div>
    <div class="charbox"><div class="avatar"><img src="${AVATAR}" alt="Nishika"></div><div class="bubble">
      <div class="charname">NISHIKA · SOC LEAD</div>
      <div class="charline">${showIntro?r.intro+'<br><br>'+p[0]:p[0]}</div>
    </div></div>
    <div class="taskfoot"><button class="btn" id="respond">Respond →</button></div>
  </div>`;
  document.getElementById('respond').onclick=openModal;
}
function openModal(){
  const p=PHASES[S.phase].parts[S.part];
  const ov=document.createElement('div');ov.className='overlay';ov.id='ov';
  ov.innerHTML=`<div class="modal"><h3>WHAT DO YOU TELL HER?</h3>
    ${p[1].map((o,i)=>`<button class="opt" data-i="${i}">${o}</button>`).join('')}
    <div class="taskfoot"><button class="btn" id="submitBtn" disabled>Submit</button></div>
  </div>`;
  document.body.appendChild(ov);
  const opts=ov.querySelectorAll('.opt');
  const submitBtn=ov.querySelector('#submitBtn');
  let selected=null;
  function selectOpt(i){
    selected=i;
    opts.forEach(b=>b.classList.remove('selected'));
    opts[i].classList.add('selected');
    submitBtn.disabled=false;
  }
  opts.forEach(b=>b.onclick=()=>selectOpt(+b.dataset.i));
  function onKey(e){
    if(e.key==='Enter'&&selected!==null){e.preventDefault();submit();}
  }
  function submit(){
    if(selected===null)return;
    document.removeEventListener('keydown',onKey);
    submitBtn.disabled=true;
    pick(selected,ov);
  }
  submitBtn.onclick=submit;
  document.addEventListener('keydown',onKey);
}
function pick(i,ov){
  const p=PHASES[S.phase].parts[S.part];
  const opts=ov.querySelectorAll('.opt');
  opts.forEach(b=>{b.disabled=true;b.classList.remove('selected');});
  if(i===p[2]){
    opts[i].classList.add('correct');
    const pts=S.attempts===0?100:S.attempts===1?60:30;
    S.score+=pts;S.flags.push(p[5]);S.attempts=0;
    setTimeout(()=>{ov.remove();showResult(true,pts,p);},600);
  }else{
    opts[i].classList.add('wrong');
    S.attempts++;S.integrity--;
    setTimeout(()=>{ov.remove();showResult(false,0,p);},600);
  }
}
function showResult(good,pts,p){
  const r=PHASES[S.phase];
  const hint=(!good&&S.attempts>=2)?`<div class="hint">Hint: ${p[4]}</div>`:'';
  const tag=good?`<span class="tag-good">${rnd(GOODLINES)}</span>`:`<span class="tag-bad">${rnd(ESCALATIONS)}</span>`;
  const flag=good?`<div class="flagline">${p[5]} · +${pts} pts</div>`:'';
  el.innerHTML=bar()+map()+`<div class="card">
    <div class="phaselabel">${r.theme} · Decision ${S.part+1}/3</div>
    <div class="charbox"><div class="avatar"><img src="${AVATAR}" alt="Nishika"></div><div class="bubble">
      <div class="charname">NISHIKA · SOC LEAD</div>
      <div class="charline">${tag}<br>${p[3]}</div>${hint}${flag}
    </div></div>
    <div class="taskfoot"><button class="btn" id="cont">${!good&&S.integrity<=0?'Regroup':'Continue'}</button></div>
  </div>`;
  document.getElementById('cont').onclick=()=>{
    if(!good&&S.integrity<=0){S.screen='phaseReset';render();return;}
    if(good)nextPart();else renderGame();
  };
}
function nextPart(){
  const r=PHASES[S.phase];
  if(S.part<r.parts.length-1){S.part++;renderGame();}
  else{S.badges.push(r.badge);S.screen='phaseComplete';render();}
}
function renderPhaseReset(){
  el.innerHTML=`<div class="center card">
    <div class="seal">⚠️</div>
    <h2>The breach escalates.</h2>
    <p style="color:var(--muted)">Nishika exhales. "We lost ground on <b>${PHASES[S.phase].name}</b>. Integrity's restored — let's go back through it and get it right this time."</p>
    <button class="btn" id="retry">Regroup and Retry</button>
  </div>`;
  document.getElementById('retry').onclick=()=>{
    S.flags=S.flags.filter(f=>!PHASES[S.phase].parts.some(p=>p[5]===f));
    S.part=0;S.integrity=5;S.attempts=0;S.screen='game';render();
  };
}
function renderPhaseComplete(){
  const r=PHASES[S.phase],bonus=S.integrity*20;S.score+=bonus;
  const last=S.phase===PHASES.length-1;
  el.innerHTML=`<div class="center card">
    <div class="seal">🏅</div>
    <h2>${r.seal} secured</h2>
    <p style="color:var(--muted)">"${r.name} is under control," Nishika says. Integrity bonus: +${bonus} pts.</p>
    <button class="btn" id="cont">${last?'Face the Final Phase':'Continue'}</button>
  </div>`;
  document.getElementById('cont').onclick=()=>{
    if(last){S.screen='victory';}
    else{S.phase++;S.part=0;S.integrity=5;S.attempts=0;S.screen='game';}
    render();
  };
}
function rankFor(score){
  if(score>=1700)return"Guardian of Chakarvyuh";
  if(score>=1300)return"Chief Incident Commander";
  if(score>=900)return"Senior SOC Analyst";
  if(score>=500)return"SOC Analyst";
  return"Trainee Responder";
}
function renderVictory(){
  el.innerHTML=`<div class="center card">
    <div class="seal">🕸️</div>
    <h2>The Deceiver is locked out. NexaCorp is safe.</h2>
    <p style="color:var(--muted)">Nishika nods. "Good work out there today."</p>
    <div class="rank">${rankFor(S.score)}</div>
    <p style="color:var(--muted)">Final score: <b>${S.score}</b> · Badges: ${S.badges.join(', ')}</p>
    <div class="flaglist">${S.flags.join('<br>')}</div>
    <button class="btn" id="restart">Run the Incident Again</button>
  </div>`;
  document.getElementById('restart').onclick=()=>{resetGame();render();};
}
render();
