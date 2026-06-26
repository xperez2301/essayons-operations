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
  if(!due) return "none";
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

function safeHtml(value){
  return String(value || "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
}

function azureMapStyle(value){
  const style = String(value || "satellite").toLowerCase();
  if(style === "roadmap" || style === "road") return "road";
  if(style === "terrain") return "grayscale_light";
  return "satellite_road_labels";
}

function dashMarkerHtml(number, color){
  const status = ["red", "amber", "green", "none"].includes(color) ? color : "green";
  return `<button class="azure-stop-marker pin-${status}" type="button" aria-label="Stop ${number} ${status} due status" title="${status.toUpperCase()} due status">${number}</button>`;
}

function dashHubHtml(){
  return `<button class="azure-hub-marker" type="button" aria-label="Hub">H</button>`;
}

function updateDashboardRoutePreview(store, stopNumber){
  const panel = document.querySelector(".route-preview-card");
  if(!panel) return;
  if(!store){
    panel.innerHTML = `<h3>Route Preview</h3><b>No route selected</b><p>Select stores on the map to build a route preview.</p><a href="/dispatch-map">Open Dispatch Map</a>`;
    return;
  }
  panel.innerHTML = `
    <h3>Pin Details</h3>
    <b>STOP ${stopNumber} - BOL ${safeHtml(store.bol || "")}</b>
    <p><b>Store:</b> ${safeHtml(store.store_name || store.origin || "Store")}</p>
    <p><b>City:</b> ${safeHtml(`${store.city || ""}${store.city && store.state ? ", " : ""}${store.state || ""}`)}</p>
    <p><b>Status:</b> ${safeHtml(store.status || "Unassigned")}</p>
    <p><b>Due:</b> ${safeHtml(store.due_date || "Not captured")}</p>
    <p><b>Racks:</b> ${safeHtml(store.expected_racks || 0)}</p>
    <p><b>Weight:</b> ${Number(store.weight || 0).toLocaleString()} lbs</p>
    <p><b>Hub:</b> ${safeHtml(store.hub || "Manual Review")}</p>
    <a href="/dispatch-map">Open Dispatch Map</a>`;
}

function fitAzureDashboardMap(map, positions){
  if(!positions.length) return;
  if(positions.length === 1){
    map.setCamera({center:positions[0], zoom:10});
    return;
  }
  map.setCamera({bounds:atlas.data.BoundingBox.fromPositions(positions), padding:70});
}

function initDashboardMap(){
  const el = document.getElementById("dashboard-map");
  if(!el) return;
  if(!window.atlas || !window.AZURE_MAPS_KEY){
    el.innerHTML = `<div class="map-missing-key"><b>Azure Maps did not load.</b><br>Check AZURE_MAPS_KEY in App Service settings.</div>`;
    return;
  }

  const stores = window.EOMS_DASHBOARD_STORES || [];
  const hubs = window.EOMS_DASHBOARD_HUBS || {};
  const map = new atlas.Map("dashboard-map", {
    center:[-97.2, 30.8],
    zoom:Number(DASH_MAP_SETTINGS.map_default_zoom || 7),
    style:azureMapStyle(DASH_MAP_SETTINGS.map_default_type),
    authOptions:{authType:"subscriptionKey", subscriptionKey:window.AZURE_MAPS_KEY}
  });

  map.events.add("ready", function(){
    const positions = [];
    Object.keys(hubs).forEach(name => {
      const h = hubs[name];
      const pos = [Number(h.lng), Number(h.lat)];
      if(!pos[0] || !pos[1] || isNaN(pos[0]) || isNaN(pos[1])) return;
      const marker = new atlas.HtmlMarker({position:pos, htmlContent:dashHubHtml()});
      map.markers.add(marker);
      map.events.add("mouseover", marker, function(){
        const panel = document.querySelector(".route-preview-card");
        if(panel) panel.innerHTML = `<h3>Hub Details</h3><b>${safeHtml(String(name).toUpperCase())} HUB</b><p>${safeHtml(h.address || "")}</p><a href="/dispatch-map">Open Dispatch Map</a>`;
      });
      map.events.add("mouseout", marker, function(){ updateDashboardRoutePreview(null); });
      positions.push(pos);
    });

    stores.filter(s => ["Unassigned","Need Review","Assigned","Dispatched"].includes(s.status || "Unassigned")).forEach((store, index) => {
      const lat = Number(store.lat);
      const lng = Number(store.lng);
      if(!lat || !lng || isNaN(lat) || isNaN(lng)) return;
      const pos = [lng, lat];
      const marker = new atlas.HtmlMarker({position:pos, htmlContent:dashMarkerHtml(index + 1, dashboardDueStatus(store))});
      map.markers.add(marker);
      map.events.add("mouseover", marker, function(){ updateDashboardRoutePreview(store, index + 1); });
      map.events.add("mouseout", marker, function(){ updateDashboardRoutePreview(null); });
      map.events.add("click", marker, function(){ window.location.href = "/dispatch-map"; });
      positions.push(pos);
    });

    fitAzureDashboardMap(map, positions);
  });
}
