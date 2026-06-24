const DASH_MAP_SETTINGS = window.EOMS_MAP_SETTINGS || {};

function parseDashboardDueDate(value){
  if(!value) return null;
  const parts = String(value).split("/");
  if(parts.length === 3) return new Date(Number(parts[2]), Number(parts[0]) - 1, Number(parts[1]));
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

function dashboardDueStatus(store){
  const due = parseDashboardDueDate(store.due_date);
  if(!due) return "green";
  const today = new Date();
  today.setHours(0,0,0,0);
  due.setHours(0,0,0,0);
  const diffDays = Math.ceil((due - today) / (1000 * 60 * 60 * 24));
  const redDays = Number(DASH_MAP_SETTINGS.due_red_days || 4);
  const amberDays = Number(DASH_MAP_SETTINGS.due_amber_days || 7);
  if(diffDays <= redDays) return "red";
  if(diffDays <= amberDays) return "amber";
  return "green";
}

function dashClusterIcon(number, color){
  const colors = {green:"#2f8a4b", amber:"#d7a53e", red:"#b7332d"};
  const fill = colors[color] || colors.green;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
    <circle cx="24" cy="24" r="20" fill="${fill}" stroke="#f4efe6" stroke-width="2"/>
    <circle cx="24" cy="24" r="23" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="1"/>
    <text x="24" y="30" text-anchor="middle" font-family="Arial" font-size="16" font-weight="900" fill="white">${number}</text>
  </svg>`;
  return {url:'data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(svg), scaledSize:new google.maps.Size(48,48), anchor:new google.maps.Point(24,24)};
}
function dashHubIcon(){
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="52" height="52" viewBox="0 0 52 52">
    <circle cx="26" cy="26" r="22" fill="#b7332d" stroke="#ffe2dd" stroke-width="3"/>
    <path d="M14 33h24v-13h-4v-5h-5v5h-6v-5h-5v5h-4v13zm8 0v-7h8v7" fill="white" opacity=".95"/>
  </svg>`;
  return {url:'data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(svg), scaledSize:new google.maps.Size(52,52), anchor:new google.maps.Point(26,26)};
}

function dashInfoHtml(title, lines){
  const safe = value => String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  return `<div style="font-family:Arial,sans-serif;color:#111827;background:#ffffff;min-width:240px;max-width:320px;padding:10px 12px;line-height:1.4;font-size:14px;font-weight:600;">
    <div style="font-size:16px;font-weight:900;color:#7f1d1d;margin-bottom:6px;">${safe(title)}</div>
    ${lines.filter(Boolean).map(line => `<div style="color:#111827;margin-top:3px;">${safe(line)}</div>`).join('')}
  </div>`;
}

function initDashboardMap(){
  const el = document.getElementById('dashboard-map');
  if(!el || !window.google || !google.maps) return;
  const stores = window.EOMS_DASHBOARD_STORES || [];
  const hubs = window.EOMS_DASHBOARD_HUBS || {};
  const map = new google.maps.Map(el,{zoom:Number(DASH_MAP_SETTINGS.map_default_zoom || 7),center:{lat:30.8,lng:-97.2},mapTypeId:DASH_MAP_SETTINGS.map_default_type || 'satellite',mapTypeControl:true,streetViewControl:false,fullscreenControl:true,gestureHandling:'greedy',styles:[{elementType:'geometry',stylers:[{color:'#17212b'}]},{elementType:'labels.text.stroke',stylers:[{color:'#111820'}]},{elementType:'labels.text.fill',stylers:[{color:'#e7e7e7'}]},{featureType:'water',elementType:'geometry',stylers:[{color:'#0c3357'}]},{featureType:'road',elementType:'geometry',stylers:[{color:'#2b333b'}]},{featureType:'poi',stylers:[{visibility:'off'}]}]});
  const bounds = new google.maps.LatLngBounds();
  Object.keys(hubs).forEach(name=>{
    const h=hubs[name]; const pos={lat:Number(h.lat),lng:Number(h.lng)};
    const marker=new google.maps.Marker({position:pos,map,title:name+' Hub',icon:dashHubIcon()});
    const info=new google.maps.InfoWindow({content:dashInfoHtml(`${name.toUpperCase()} HUB`, [h.address])});
    marker.addListener('click',()=>info.open(map,marker));
    bounds.extend(pos);
  });
  const activeStores=stores.filter(s=>{
    const lat=Number(s.lat), lng=Number(s.lng);
    return ['Unassigned','Need Review','Assigned','Dispatched'].includes(s.status || 'Unassigned') && lat && lng && !isNaN(lat) && !isNaN(lng);
  });
  activeStores.forEach((store,index)=>{
    const lat=Number(store.lat), lng=Number(store.lng);
    if(!lat || !lng || isNaN(lat) || isNaN(lng)) return;
    const pos={lat,lng};
    const color = dashboardDueStatus(store);
    const marker=new google.maps.Marker({
      position:pos,map,
      title:`${index+1}. BOL ${store.bol || ''} - ${store.store_name || store.origin || 'Store'}`,
      icon:dashClusterIcon(index+1, color)
    });
    const info=new google.maps.InfoWindow({
      content:dashInfoHtml(`STOP ${index+1} - BOL ${store.bol || ''}`, [
        store.store_name || store.origin || 'Store',
        `${store.city || ''}, ${store.state || ''}`,
        `Status: ${store.status || 'Unassigned'}`,
        `Due: ${store.due_date || 'Not captured'}`,
        `Racks: ${store.expected_racks || 0}`,
        `Weight: ${Number(store.weight || 0).toLocaleString()} lbs`
      ])
    });
    marker.addListener('click',()=>info.open(map,marker));
    bounds.extend(pos);
  });
  if(!bounds.isEmpty()) map.fitBounds(bounds);
}
