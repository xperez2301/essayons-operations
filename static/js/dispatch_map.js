let map;
let markers = {};
const stores = window.EOMS_STORES || [];
const hubs = window.EOMS_HUBS || {};
const MAX_CAPACITY = window.MAX_PAYLOAD || 25001;
const CAN_VIEW_FINANCIALS = !!window.EOMS_CAN_VIEW_FINANCIALS;
const MAP_SETTINGS = window.EOMS_MAP_SETTINGS || {};
let selectedOrder = [];
let activeClusterInfo = null;

function parseDueDate(value){
    if(!value) return null;
    const parts = String(value).split("/");
    if(parts.length === 3){
        return new Date(Number(parts[2]), Number(parts[0]) - 1, Number(parts[1]));
    }
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
}

function dueStatus(store){
    const due = parseDueDate(store.due_date);
    if(!due) return "none";
    const today = new Date();
    today.setHours(0,0,0,0);
    due.setHours(0,0,0,0);
    const diffDays = Math.ceil((due - today) / (1000 * 60 * 60 * 24));
    const redDays = Number(MAP_SETTINGS.due_red_days || 4);
    const amberDays = Number(MAP_SETTINGS.due_amber_days || 7);
    if(diffDays <= redDays) return "red";
    if(diffDays <= amberDays) return "amber";
    return "green";
}

function dueLabel(store){
    const status = dueStatus(store);
    const text = store.due_date || "Not captured";
    const label = status === "none" ? "NO DATE" : status.toUpperCase();
    return `<span class="route-due-chip due-${status}">Due: ${text} (${label})</span>`;
}

function rackFormula(store){
    const posts = Number(store.corner_posts || 0);
    const racks = Number(store.expected_racks || 0);
    return `${posts.toLocaleString()} corner posts / 4 = ${racks.toLocaleString()} racks`;
}

function azureMapStyle(value){
    const style = String(value || "satellite").toLowerCase();
    if(style === "roadmap" || style === "road") return "road";
    if(style === "terrain") return "grayscale_light";
    return "satellite_road_labels";
}

function pinIcon(number, color){
    const status = ["red", "amber", "green", "none"].includes(color) ? color : "green";
    return `<button class="azure-stop-marker pin-${status}" type="button" aria-label="Stop ${number} ${status} due status" title="${status.toUpperCase()} due status">${number}</button>`;
}

function hubIcon(){
    return `<button class="azure-hub-marker" type="button" aria-label="Hub">H</button>`;
}

function mapInfoHtml(title, lines){
    const safe = value => String(value || "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
    return `<div style="font-family:Arial,sans-serif;color:#111827;background:#ffffff;min-width:240px;max-width:320px;padding:10px 12px;line-height:1.4;font-size:14px;font-weight:600;">
        <div style="font-size:16px;font-weight:900;color:#7f1d1d;margin-bottom:6px;">${safe(title)}</div>
        ${lines.filter(Boolean).map(line => `<div style="color:#111827;margin-top:3px;">${safe(line)}</div>`).join("")}
    </div>`;
}

function materialValue(store, key){
    const value = Number(store[key] || 0);
    return Number.isFinite(value) ? value : 0;
}

function materialEditorHtml(store){
    const id = store.id || store.bol || "";
    const bol = String(store.bol || "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
    return `
        <div class="material-editor" data-store-id="${id}" data-bol="${bol}">
            <label>84<input data-material="corner_posts" type="number" min="0" step="1" value="${materialValue(store, "corner_posts")}"></label>
            <label>40<input data-material="drb40" type="number" min="0" step="1" value="${materialValue(store, "drb40")}"></label>
            <label>48<input data-material="drb48" type="number" min="0" step="1" value="${materialValue(store, "drb48")}"></label>
            <label>Wood<input data-material="wood_shelf" type="number" min="0" step="1" value="${materialValue(store, "wood_shelf")}"></label>
            <button class="tiny-btn" type="button" onclick="saveMapBoardMaterials(this.closest('.material-editor').dataset.storeId)">Save Load</button>
            <button class="tiny-btn danger-mini" type="button" onclick="deleteMapBoardBol(this.closest('.material-editor').dataset.storeId,this.closest('.material-editor').dataset.bol)">Delete</button>
        </div>`;
}

function syncSelectedMarkerVisibility(){
    if(!map || !markers) return;
    Object.keys(markers).forEach(id => {
        if(!markers[id]) return;
        setMarkerVisible(markers[id], !selectedOrder.includes(id));
    });
}

function setMarkerVisible(marker, visible){
    if(!map || !marker) return;
    if(visible && !marker._eomsOnMap){
        map.markers.add(marker);
        marker._eomsOnMap = true;
    }else if(!visible && marker._eomsOnMap){
        map.markers.remove(marker);
        marker._eomsOnMap = false;
    }
}

function focusStoreCard(storeId){
    document.querySelectorAll(".store-card").forEach(card => card.classList.remove("active-store"));
    const box = document.querySelector(`.store-box[data-store-id="${storeId}"]`);
    if(!selectedOrder.includes(storeId)){
        selectedOrder.push(storeId);
    }
    if(box){
        const card = box.closest(".store-card");
        if(card){
            card.classList.add("active-store");
            card.scrollIntoView({behavior:"smooth", block:"center"});
        }
    }
    renderStores();
    syncSelectedMarkerVisibility();
    updateTotals();
}

function selectStoreFromMap(storeId){
    focusStoreCard(storeId);
    if(activeClusterInfo) activeClusterInfo.close();
    previewRoute();
}
window.selectStoreFromMap = selectStoreFromMap;


function visibleUnassignedStores(){ return stores.filter(s => s.status === "Unassigned" && !selectedOrder.includes(s.id)); }

function selectedIds(){
    return [...selectedOrder];
}

function updateSelectionOrder(){
    const ids = selectedIds();
    ids.forEach(id => { if(!selectedOrder.includes(id)) selectedOrder.push(id); });
    selectedOrder = selectedOrder.filter(id => ids.includes(id));
}


function selectAllVisible(){
    visibleUnassignedStores().forEach(store => { if(!selectedOrder.includes(store.id)) selectedOrder.push(store.id); });
    renderStores();
    syncSelectedMarkerVisibility();
    updateTotals();
}
function clearSelection(){
    selectedOrder = [];
    renderStores();
    syncSelectedMarkerVisibility();
    updateTotals();
}
function selectDueToday(){
    const today = new Date(); today.setHours(0,0,0,0);
    visibleUnassignedStores().forEach(store => {
        const due = parseDueDate(store.due_date);
        if(due){ due.setHours(0,0,0,0); }
        const shouldSelect = due && due <= today;
        if(shouldSelect && !selectedOrder.includes(store.id)) selectedOrder.push(store.id);
    });
    renderStores();
    syncSelectedMarkerVisibility();
    updateTotals();
}
async function loadDrivers(){
    const select = document.getElementById("driver-select");
    if(!select) return;
    try{
        const response = await fetch("/api/drivers");
        const data = await response.json();
        if(!data.ok) return;
        const existing = select.value;
        select.innerHTML = '<option value="">Select Driver</option>';
        (data.drivers || []).forEach(driver => {
            const option = document.createElement("option");
            option.value = driver.name || driver.username;
            option.dataset.phone = driver.phone || "";
            option.textContent = (driver.name || driver.username) + (driver.cities && driver.cities.length ? " â€” " + driver.cities.join(", ") : "");
            if(existing && option.value === existing) option.selected = true;
            select.appendChild(option);
        });
    }catch(err){ console.warn("Unable to load drivers", err); }
}

function renderStores(){
    const container = document.getElementById("available-stores");
    container.innerHTML = "";
    const available = visibleUnassignedStores();

    if(available.length === 0){
        container.innerHTML = "<p class='muted'>No unassigned stores. Import RMS BOLs or check Need Review.</p>";
        return;
    }

    available.forEach(store => {
        const label = document.createElement("label");
        label.className = "store-card";
        label.dataset.storeId = store.id;
        label.innerHTML = `
            <input type="checkbox" class="store-box" data-store-id="${store.id}" data-racks="${store.expected_racks || 0}" data-weight="${store.weight || 0}">
            <div>
                <strong>${store.store_name || store.origin || "Unknown Store"}</strong>
                <span>BOL ${store.bol || ""} â€¢ Origin ${store.origin || ""}</span>
                <span>${store.city || ""}, ${store.state || ""} â€¢ ${store.expected_racks || 0} racks</span>
                <span>${dueLabel(store)}</span>
                <small>${store.hub || "Manual Review"}</small><br><a class="mini-link" href="/bol-live/${store.bol}" target="_blank" onclick="event.stopPropagation()">Live BOL</a> <a class="mini-link" href="/bol-view/${store.id}" target="_blank" onclick="event.stopPropagation()">Saved Copy</a> <a class="mini-link" href="/bol-print/${store.id}" target="_blank" onclick="event.stopPropagation()">Print</a>
            </div>
        `;
        container.appendChild(label);
    });
}

function updateTotals(){
    let count = 0, racks = 0, weight = 0;

    selectedOrder.forEach(id => {
        const store = stores.find(item => item.id === id);
        if(!store) return;
        count++;
        racks += Number(store.expected_racks || 0);
        weight += Number(store.weight || 0);
    });

    document.getElementById("store-count").innerText = count;
    document.getElementById("rack-count").innerText = racks;
    document.getElementById("weight-count").innerText = weight;
    document.getElementById("remaining-capacity").innerText = MAX_CAPACITY - weight;

    const status = document.getElementById("capacity-status");
    status.className = "";
    if(weight > MAX_CAPACITY){ status.innerText = "OVER LIMIT"; status.classList.add("over"); }
    else if(weight > 22000){ status.innerText = "WARNING"; status.classList.add("warning"); }
    else{ status.innerText = "SAFE"; status.classList.add("safe"); }

    const gauge = document.getElementById("payload-gauge-fill");
    if(gauge){
        gauge.style.width = Math.min(100, (weight / MAX_CAPACITY) * 100) + "%";
        gauge.className = weight > MAX_CAPACITY ? "over" : weight > 22000 ? "warning" : "safe";
    }
    const preview = document.getElementById("route-preview");
    if(preview && selectedOrder.length){
        preview.innerHTML = selectedOrder.map((id, index) => {
            const store = stores.find(item => item.id === id);
            return store ? `<div class="preview-stop"><b>${index + 1}</b><div><strong>${store.store_name || store.origin || "Store"}</strong>${dueLabel(store)}<small>BOL ${store.bol || ""} &middot; Status ${store.status || "Unassigned"} &middot; ${rackFormula(store)} &middot; ${Number(store.weight || 0).toLocaleString()} lbs</small></div></div>` : "";
        }).join("");
    }else if(preview){
        preview.innerHTML = "<p class='muted'>Select stores to build the route. The first store selected becomes stop 1.</p>";
    }
}

document.addEventListener("change", updateTotals);

async function previewRoute(){
    const ids = selectedOrder.length ? selectedOrder : selectedIds();
    const mode = document.getElementById("route-mode").value;

    if(ids.length === 0){
        alert("Select stores first");
        return;
    }

    const response = await fetch("/api/preview-route", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({store_ids: ids, mode: mode})
    });

    const data = await response.json();
    if(!data.ok){
        alert(data.message || "Preview failed");
        return;
    }

    renderPreview(data);
}

function renderPreview(data){
    const m = data.metrics;
    let html = `
        <div class="route-card">
            <h4>Route Preview</h4>
            <p><b>Hub:</b> ${data.hub}</p>
            <p><b>Mode:</b> ${data.mode === "optimized" ? "Nearest Stop From Hub" : "Selection Order"}</p>
            <p><b>Stores:</b> ${m.store_count}</p>
            <p><b>Racks:</b> ${m.racks}</p>
            <p><b>Pieces:</b> ${m.pieces}</p>
            <p><b>Weight:</b> ${m.weight} lbs</p>
            <p><b>Remaining:</b> ${m.remaining_capacity} lbs</p>
            <p><b>Mileage:</b> ${m.mileage} mi</p>
            ${CAN_VIEW_FINANCIALS ? `<p><b>Revenue:</b> $${m.revenue}</p><p><b>Driver Pay:</b> $${m.driver_pay}</p>` : ""}
            <p><b>Status:</b> <span class="${m.status === "SAFE" ? "safe" : m.status === "WARNING" ? "warning" : "over"}">${m.status}</span></p>
            <hr>
            <h4>Stop Order</h4>
    `;

    data.stores.forEach((s, index) => {
        html += `<div class="preview-stop"><b>${index + 1}</b><div><strong>${s.store_name || s.origin || "Store"}</strong>${dueLabel(s)}<small>BOL ${s.bol || ""} &middot; Status ${s.status || "Unassigned"} &middot; ${rackFormula(s)} &middot; ${Number(s.weight || 0).toLocaleString()} lbs</small></div></div>`;
    });

    html += "</div>";
    document.getElementById("route-preview").innerHTML = html;
}

async function assignDriver(){
    const driver = document.getElementById("driver-select").value;
    if(!driver){ alert("Select a driver"); return; }

    const ids = selectedOrder.length ? selectedOrder : selectedIds();
    if(ids.length === 0){ alert("Select stores first"); return; }

    const mode = document.getElementById("route-mode").value;
    const selectedDriverOption = document.getElementById("driver-select").selectedOptions[0];
    const driverPhone = selectedDriverOption ? selectedDriverOption.dataset.phone || "" : "";

    const response = await fetch("/api/assign-route", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({driver: driver, driver_phone: driverPhone, store_ids: ids, mode: mode})
    });

    const data = await response.json();
    if(!data.ok){
        alert(data.message || "Assignment failed");
        return;
    }

    const route = data.route;
    const routeBlock = document.createElement("div");
    routeBlock.className = "route-card";
    routeBlock.innerHTML = `
        <h4>${route.route_number}</h4>
        <p><b>Driver:</b> ${driver}</p>
        <p><b>Hub:</b> ${route.hub}</p>
        <p><b>Miles:</b> ${route.metrics.mileage}</p>
        ${CAN_VIEW_FINANCIALS ? `<p><b>Revenue:</b> $${route.metrics.revenue}</p><p><b>Driver Pay:</b> $${route.metrics.driver_pay}</p>` : ""}
        <button class="primary-btn dispatch-route-btn" onclick="dispatchRoute('${route.id}', this)">Dispatch Route &amp; Send SMS</button>
    `;

    data.assigned.forEach(store => {
        const row = document.createElement("div");
        row.className = "route-row";
        row.innerHTML = `<span>${store.store_name || store.origin}<br><small>BOL ${store.bol || ""}</small></span>`;

        const btn = document.createElement("button");
        btn.innerText = "Unassign";
        btn.onclick = async function(){ await unassignStore(store.id, row); };

        row.appendChild(btn);
        routeBlock.appendChild(row);

        const original = stores.find(s => s.id === store.id);
        if(original){
            original.status = "Assigned";
            original.assigned_driver = driver;
        }
    });

    document.getElementById("driver-results").appendChild(routeBlock);
    selectedOrder = [];
    renderStores();
    syncSelectedMarkerVisibility();
    renderMapDispatchBoardLive();
    updateTotals();
    document.getElementById("route-preview").innerHTML = "<p class='safe'>Route assigned. Dispatch it from the Assigned Queue below.</p>";
}

async function dispatchRoute(routeId, button){
    button.disabled = true;
    button.textContent = "Dispatching...";
    try{
        const response = await fetch("/api/dispatch-route", {
            method:"POST", headers:{"Content-Type":"application/json"},
            body:JSON.stringify({route_id:routeId})
        });
        const data = await response.json();
        if(!data.ok) throw new Error(data.message || "Dispatch failed");
        const smsResponse = await fetch("/api/send-route-sms", {
            method:"POST", headers:{"Content-Type":"application/json"},
            body:JSON.stringify({route_id:routeId})
        });
        const sms = await smsResponse.json();
        button.textContent = sms.ok ? "Dispatched - SMS Sent" : "Dispatched - SMS Not Configured";
        button.className = "secondary-btn dispatch-route-btn";
        renderMapDispatchBoardLive();
    }catch(err){
        button.disabled = false;
        button.textContent = "Dispatch Route & Send SMS";
        alert(err.message);
    }
}
window.dispatchRoute = dispatchRoute;

async function unassignStore(storeId, row){
    const response = await fetch("/api/unassign-store", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({store_id:storeId})
    });

    const data = await response.json();

    if(data.ok && data.store){
        const original = stores.find(s => s.id === storeId);
        if(original){
            original.status = "Unassigned";
            original.assigned_driver = "";
        }

        if(markers[storeId]) setMarkerVisible(markers[storeId], true);

        row.remove();
        renderStores();
        updateTotals();
    }
}


function hoverStorePreview(store, stopNumber){
    const preview = document.getElementById("route-preview");
    if(!preview || !store) return;
    const originName = store.origin_name || store.store_name || store.origin || "Not captured";
    const destinationName = store.destination_name || store.destination || "Not captured";
    const address = store.full_address || [
        store.address || store.origin_address || "",
        store.city || store.origin_city || "",
        store.state || store.origin_state || "",
        store.zip || store.origin_zip || ""
    ].filter(Boolean).join(", ");
    const review = (store.review_reasons && store.review_reasons.length)
        ? store.review_reasons.join(", ")
        : ((store.review_warnings && store.review_warnings.length) ? store.review_warnings.join(", ") : "Ready");
    preview.innerHTML = `
        <div class="route-card hover-store-card">
            <h4>Pin Details</h4>
            <p><b>Stop:</b> ${stopNumber}</p>
            <p><b>BOL:</b> ${store.bol || ""}</p>
            <p><b>Origin/Pickup:</b> ${originName}</p>
            <p><b>Destination:</b> ${destinationName}</p>
            <p><b>Address:</b> ${address || "Not captured"}</p>
            <p><b>City:</b> ${store.city || ""}${store.city && store.state ? ", " : ""}${store.state || ""}</p>
            <p><b>Status:</b> ${store.status || "Unassigned"}</p>
            <p><b>Review:</b> ${review}</p>
            <p>${dueLabel(store)}</p>
            <p><b>Racks:</b> ${rackFormula(store)}</p>
            <p><b>Materials:</b> CP ${store.corner_posts || 0} / DRB40 ${store.drb40 || 0} / DRB48 ${store.drb48 || 0} / Wood ${store.wood_shelf || 0}</p>
            <p><b>Weight:</b> ${Number(store.weight || 0).toLocaleString()} lbs</p>
            <p><b>Hub:</b> ${store.hub || "Manual Review"}</p>
            <small>Move off the pin to return to route preview. Click the pin to select the stop.</small>
        </div>`;
}

function restoreRoutePreviewAfterHover(){
    updateTotals();
}

function initMap(){
    const mapEl = document.getElementById("map");
    if(!window.atlas || !window.AZURE_MAPS_KEY){
        const el = document.getElementById("map");
        if(el) el.innerHTML = "<div class='map-missing-key'><b>Azure Maps did not load.</b><br>Check AZURE_MAPS_KEY in App Service settings.</div>";
        renderStores();
        updateTotals();
        if (typeof renderMapDispatchBoard === "function") renderMapDispatchBoard();
        return;
    }
    map = new atlas.Map(mapEl, {
        zoom: Number(MAP_SETTINGS.map_default_zoom || 7),
        center: [-97.2, 30.8],
        style: azureMapStyle(MAP_SETTINGS.map_default_type),
        view: "Auto",
        authOptions:{authType:"subscriptionKey", subscriptionKey:window.AZURE_MAPS_KEY}
    });

    map.events.add("ready", function(){
        const positions = [];

        Object.keys(hubs).forEach(hubName => {
            const hub = hubs[hubName];
            const hubPos = [Number(hub.lng), Number(hub.lat)];
            if(!hubPos[0] || !hubPos[1] || isNaN(hubPos[0]) || isNaN(hubPos[1])) return;
            const marker = new atlas.HtmlMarker({position:hubPos, htmlContent:hubIcon()});
            marker._eomsOnMap = true;
            map.markers.add(marker);
            map.events.add("mouseover", marker, () => {
                const preview = document.getElementById("route-preview");
                if(preview){
                    preview.innerHTML = `<div class="route-card"><h4>Hub Details</h4><p><b>${hubName.toUpperCase()} HUB</b></p><p>${hub.address || ""}</p></div>`;
                }
            });
            map.events.add("mouseout", marker, restoreRoutePreviewAfterHover);
            positions.push(hubPos);
        });

        let pinNumber = 1;

        stores.forEach(store => {
            let lat = Number(store.lat);
            let lng = Number(store.lng);
            if(!lat || !lng || isNaN(lat) || isNaN(lng)) return;

            const pos = [lng, lat];
            const thisPinNumber = pinNumber++;
            const color = dueStatus(store);

            markers[store.id] = new atlas.HtmlMarker({
                position: pos,
                htmlContent: pinIcon(thisPinNumber, color)
            });
            markers[store.id]._eomsOnMap = true;
            map.markers.add(markers[store.id]);

            positions.push(pos);
            map.events.add("mouseover", markers[store.id], () => hoverStorePreview(store, thisPinNumber));
            map.events.add("mouseout", markers[store.id], restoreRoutePreviewAfterHover);
            map.events.add("click", markers[store.id], () => {
                if((store.status || "Unassigned") === "Unassigned"){
                    focusStoreCard(store.id);
                }else{
                    hoverStorePreview(store, thisPinNumber);
                }
            });
        });

        renderStores();

        const visibleMarkers = Object.keys(markers).length;
        if(positions.length === 1){
            map.setCamera({center:positions[0], zoom:10});
        }else if(positions.length > 1){
            map.setCamera({bounds:atlas.data.BoundingBox.fromPositions(positions), padding:70});
        }
        if(!visibleMarkers && mapEl){
            mapEl.insertAdjacentHTML("beforeend", "<div class='map-missing-key'><b>No pinned BOLs yet.</b><br>Import BOLs or click Fix / Reload Pins.</div>");
        }
    });
}


function getSelectedStoreIds(){
    return [...selectedOrder];
}

async function buildRoute(mode){
    const storeIds = getSelectedStoreIds();
    if(!storeIds.length){
        alert("Select at least one store first.");
        return;
    }

    const driverSelect = document.getElementById("driver-select");
    const driver = driverSelect ? driverSelect.value : "";

    const previewResponse = await fetch("/api/preview-route", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({store_ids: storeIds, mode})
    });
    const preview = await previewResponse.json();
    if(!preview.ok){
        alert(preview.message || "Unable to preview route.");
        return;
    }

    const metrics = preview.metrics || {};
    const confirmText =
        "Build route using " + (mode === "selection" ? "your selected order" : "optimized nearest-stop order") + "?\\n\\n" +
        "Stores: " + metrics.store_count + "\\n" +
        "Racks: " + metrics.racks + "\\n" +
        "Weight: " + metrics.weight + " lbs\\n" +
        "Remaining: " + metrics.remaining_capacity + " lbs\\n" +
        "Status: " + metrics.status;

    if(!confirm(confirmText)) return;

    const assignResponse = await fetch("/api/assign-route", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({store_ids: storeIds, mode, driver})
    });
    const result = await assignResponse.json();

    if(!result.ok){
        alert(result.message || "Route assignment failed.");
        return;
    }

    alert("Route built: " + result.route.route_number);
    window.location.href = "/route-builder";
}


document.addEventListener("change", function(e){
    if(e.target && e.target.classList.contains("store-box")){
        const id = e.target.dataset.storeId;
        if(e.target.checked){
            if(!selectedOrder.includes(id)) selectedOrder.push(id);
        }else{
            selectedOrder = selectedOrder.filter(x => x !== id);
        }
        renderStores();
        syncSelectedMarkerVisibility();
        updateTotals();
    }
});



function money(n){
    return "$" + Number(n || 0).toFixed(2);
}

function renderMapDispatchBoard(){
    const board = document.getElementById("map-dispatch-board");
    if(!board || typeof stores === "undefined") return;

    const statuses = ["Need Review", "Unassigned", "Assigned", "Dispatched", "Completed"];
    const byStatus = {};
    statuses.forEach(s => byStatus[s] = []);
    stores.forEach(store => {
        const status = store.status || "Unassigned";
        if(!byStatus[status]) byStatus[status] = [];
        byStatus[status].push(store);
    });

    const activeStores = stores.filter(s => ["Need Review","Unassigned","Assigned","Dispatched"].includes(s.status || "Unassigned"));
    const racks = activeStores.reduce((sum, s) => sum + Number(s.expected_racks || 0), 0);
    const weight = activeStores.reduce((sum, s) => sum + Number(s.weight || 0), 0);
    const revenue = racks * 19 * 0.95;
    const driverPay = racks * 19 * 0.30;

    const metrics = document.getElementById("map-board-metrics");
    if(metrics){
        metrics.innerHTML = `
            <div><span>Need Review</span><strong>${byStatus["Need Review"].length}</strong></div>
            <div><span>Unassigned</span><strong>${byStatus["Unassigned"].length}</strong></div>
            <div><span>Assigned</span><strong>${byStatus["Assigned"].length}</strong></div>
            <div><span>Dispatched</span><strong>${byStatus["Dispatched"].length}</strong></div>
            <div><span>Completed</span><strong>${byStatus["Completed"].length}</strong></div>
            <div><span>Racks</span><strong>${racks.toFixed(1)}</strong></div>
            <div><span>Weight</span><strong>${weight.toFixed(0)} lbs</strong></div>
            <div><span>Revenue</span><strong>${money(revenue)}</strong></div>
            <div><span>Driver Pay</span><strong>${money(driverPay)}</strong></div>
        `;
    }

    statuses.forEach(status => {
        const col = document.querySelector(`.map-board-column[data-status="${status}"]`);
        if(!col) return;
        const list = col.querySelector(".map-board-list");
        const count = col.querySelector("h4 span");
        const items = byStatus[status] || [];
        if(count) count.textContent = items.length;

        list.innerHTML = items.slice(0, 30).map(store => {
            const color = dueStatus(store);
            const actions = mapBoardActions(store, status);
            return `
                <div class="map-board-card">
                    <div class="map-board-card-head">
                        <b>BOL ${store.bol || ""}</b>
                        <span class="due-chip due-${color}">${store.due_date || "No Due"}</span>
                    </div>
                    <div class="map-board-store">${store.store_name || store.origin_name || "Store"} / ${store.origin || ""}</div>
                    <div class="map-board-sub">${store.city || ""}, ${store.state || ""} â€¢ ${store.expected_racks || 0} racks â€¢ ${store.weight || 0} lbs</div>
                    ${materialEditorHtml(store)}
                    ${store.assigned_driver ? `<div class="map-board-driver">Driver: <b>${store.assigned_driver}</b></div>` : ""}
                    <div class="map-board-actions">
                        <a class="mini-link" href="/bol-live/${store.bol}" target="_blank">Live</a>
                        <a class="mini-link" href="/bol-view/${store.id}" target="_blank">Saved</a>
                        <a class="mini-link" href="/bol-print/${store.id}" target="_blank">Print</a>
                        <a class="mini-link" href="/all-bols?q=${encodeURIComponent(store.bol || store.id)}">Edit</a>
                        ${actions}
                    </div>
                </div>
            `;
        }).join("") || `<p class="muted small-muted">No items.</p>`;
    });
}

function mapBoardActions(store, status){
    if(status === "Need Review"){
        return `<button class="tiny-btn" onclick="setMapBoardStatus('${store.id}','Unassigned')">Approve</button>`;
    }
    if(status === "Unassigned"){
        return `<button class="tiny-btn" onclick="focusStoreCard('${store.id}')">Select</button>`;
    }
    if(status === "Assigned"){
        return `<button class="tiny-btn" onclick="setMapBoardStatus('${store.id}','Dispatched')">Dispatch</button>
                <button class="tiny-btn" onclick="setMapBoardStatus('${store.id}','Unassigned')">Unassign</button>`;
    }
    if(status === "Dispatched"){
        return `<button class="tiny-btn" onclick="setMapBoardStatus('${store.id}','Completed')">Complete</button>`;
    }
    return "";
}

async function setMapBoardStatus(storeId, status){
    if(!confirm("Move this BOL to " + status + "?")) return;
    const response = await fetch("/api/store-status", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({store_id:storeId, status:status})
    });
    const data = await response.json();
    if(!data.ok){
        alert(data.message || "Unable to update status.");
        return;
    }
    location.reload();
}

async function saveMapBoardMaterials(storeId){
    const box = document.querySelector(`.material-editor[data-store-id="${storeId}"]`);
    if(!box){
        alert("Material editor not found.");
        return;
    }
    const payload = {};
    box.querySelectorAll("[data-material]").forEach(input => {
        payload[input.dataset.material] = input.value;
    });
    const response = await fetch("/api/bol/" + encodeURIComponent(storeId), {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload)
    });
    const data = await response.json();
    if(!data.ok){
        alert(data.message || "Unable to save material counts.");
        return;
    }
    alert(`Saved load counts. Racks recalculated to ${data.store.expected_racks || 0}.`);
    location.reload();
}

async function deleteMapBoardBol(storeId, bol){
    const label = bol || storeId;
    if(!confirm("Delete BOL " + label + " completely? This removes it from EOMS and deletes saved BOL files so Auto Grab can pull it fresh.")){
        return;
    }
    const response = await fetch("/api/delete-bol", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({store_id:storeId, bol:bol})
    });
    const data = await response.json();
    if(!data.ok){
        alert(data.message || "Unable to delete BOL.");
        return;
    }
    alert(data.message || "BOL deleted.");
    location.reload();
}

function toggleMapBoard(){
    const grid = document.getElementById("map-board-grid");
    const metrics = document.getElementById("map-board-metrics");
    if(grid) grid.classList.toggle("hidden");
    if(metrics) metrics.classList.toggle("hidden");
}




async function renderMapDispatchBoardLive(){
    const board = document.getElementById("map-dispatch-board");
    if(!board) return;

    try{
        const response = await fetch("/api/dispatch-board-live");
        const data = await response.json();
        if(!data.ok){
            console.warn("Dispatch board live API failed", data);
            if (typeof renderMapDispatchBoard === "function") renderMapDispatchBoard();
            return;
        }

        const liveStores = data.stores || [];
        const statuses = ["Need Review", "Unassigned", "Assigned", "Dispatched", "Completed"];
        const byStatus = {};
        statuses.forEach(s => byStatus[s] = []);

        liveStores.forEach(store => {
            let status = store.status || "Unassigned";
            if(!byStatus[status]) status = "Unassigned";
            byStatus[status].push(store);
        });

        const metrics = document.getElementById("map-board-metrics");
        if(metrics){
            metrics.innerHTML = `
                <div><span>Need Review</span><strong>${byStatus["Need Review"].length}</strong></div>
                <div><span>Unassigned</span><strong>${byStatus["Unassigned"].length}</strong></div>
                <div><span>Assigned</span><strong>${byStatus["Assigned"].length}</strong></div>
                <div><span>Dispatched</span><strong>${byStatus["Dispatched"].length}</strong></div>
                <div><span>Completed</span><strong>${byStatus["Completed"].length}</strong></div>
                <div><span>Racks</span><strong>${Number(data.metrics.racks || 0).toFixed(1)}</strong></div>
                <div><span>Weight</span><strong>${Number(data.metrics.weight || 0).toFixed(0)} lbs</strong></div>
                <div><span>Revenue</span><strong>$${Number(data.metrics.revenue || 0).toFixed(2)}</strong></div>
                <div><span>Driver Pay</span><strong>$${Number(data.metrics.driver_pay || 0).toFixed(2)}</strong></div>
            `;
        }

        statuses.forEach(status => {
            const col = document.querySelector(`.map-board-column[data-status="${status}"]`);
            if(!col) return;

            const list = col.querySelector(".map-board-list");
            const count = col.querySelector("h4 span");
            const items = byStatus[status] || [];
            if(count) count.textContent = items.length;

            list.innerHTML = items.slice(0, 50).map(store => {
                const color = typeof dueStatus === "function" ? dueStatus(store) : "green";
                const actions = typeof mapBoardActions === "function" ? mapBoardActions(store, status) : "";
                return `
                    <div class="map-board-card">
                        <div class="map-board-card-head">
                            <b>BOL ${store.bol || ""}</b>
                            <span class="due-chip due-${color}">${store.due_date || "No Due"}</span>
                        </div>
                        <div class="map-board-store">${store.store_name || store.origin_name || "Store"} / ${store.origin || ""}</div>
                        <div class="map-board-sub">${store.city || ""}, ${store.state || ""} â€¢ ${store.expected_racks || 0} racks â€¢ ${store.weight || 0} lbs</div>
                        ${materialEditorHtml(store)}
                        ${store.assigned_driver ? `<div class="map-board-driver">Driver: <b>${store.assigned_driver}</b></div>` : ""}
                        <div class="map-board-actions">
                            <a class="mini-link" href="/bol-live/${store.bol}" target="_blank">Live</a>
                            <a class="mini-link" href="/bol-view/${store.id}" target="_blank">Saved</a>
                            <a class="mini-link" href="/bol-print/${store.id}" target="_blank">Print</a>
                            <a class="mini-link" href="/all-bols?q=${encodeURIComponent(store.bol || store.id)}">Edit</a>
                            ${actions}
                        </div>
                    </div>
                `;
            }).join("") || `<p class="muted small-muted">No items.</p>`;
        });
    }catch(err){
        console.error("Dispatch Board live render error", err);
        if (typeof renderMapDispatchBoard === "function") renderMapDispatchBoard();
    }
}

document.addEventListener("DOMContentLoaded", function(){
    if (typeof renderMapDispatchBoard === "function") renderMapDispatchBoard();
    setTimeout(renderMapDispatchBoardLive, 500);
    const refreshSeconds = Number(MAP_SETTINGS.map_live_refresh_seconds || 30);
    if(refreshSeconds >= 10){
        setInterval(renderMapDispatchBoardLive, refreshSeconds * 1000);
    }
    loadDrivers();
});



// Local fallback: render the store list/board even if Azure Maps does not load.
document.addEventListener("DOMContentLoaded", function(){
    try {
        if (document.getElementById("available-stores")) {
            renderStores();
            updateTotals();
        }
        setTimeout(function(){
            var mapBox = document.getElementById("map");
            if (mapBox && !map) {
                if (!mapBox.innerHTML.trim()) {
                    mapBox.innerHTML = "<div class='map-missing-key'>Map did not load locally. Check Settings for Azure Maps key, then click Fix / Reload Pins.</div>";
                }
            }
        }, 2500);
    } catch (err) {
        console.error("Dispatch Map local fallback failed:", err);
    }
});

window.initMap = initMap;

