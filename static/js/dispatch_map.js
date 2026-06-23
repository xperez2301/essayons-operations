let map;
let markers = {};
const stores = window.EOMS_STORES || [];
const hubs = window.EOMS_HUBS || {};
const MAX_CAPACITY = window.MAX_PAYLOAD || 25001;
const CAN_VIEW_FINANCIALS = !!window.EOMS_CAN_VIEW_FINANCIALS;
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
    if(!due) return "green";
    const today = new Date();
    today.setHours(0,0,0,0);
    due.setHours(0,0,0,0);
    const diffDays = Math.ceil((due - today) / (1000 * 60 * 60 * 24));
    // Due-date color rule:
    // - red: overdue or 4 days or less remaining
    // - amber: 5 through 7 days remaining
    // - green: more than 7 days remaining, or no due date captured
    if(diffDays <= 4) return "red";
    if(diffDays <= 7) return "amber";
    return "green";
}

function pinIcon(number, color){
    const colors = {green:"#2f8a4b", amber:"#d7a53e", red:"#b7332d"};
    const fill = colors[color] || colors.green;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
      <circle cx="24" cy="24" r="20" fill="${fill}" stroke="#f4efe6" stroke-width="2"/>
      <circle cx="24" cy="24" r="23" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="1"/>
      <text x="24" y="30" text-anchor="middle" font-family="Arial" font-size="16" font-weight="900" fill="white">${number}</text>
    </svg>`;
    return {
        url: "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg),
        scaledSize: new google.maps.Size(48,48),
        anchor: new google.maps.Point(24,24)
    };
}

function hubIcon(){
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="52" height="52" viewBox="0 0 52 52">
      <circle cx="26" cy="26" r="22" fill="#b7332d" stroke="#ffe2dd" stroke-width="3"/>
      <path d="M14 33h24v-13h-4v-5h-5v5h-6v-5h-5v5h-4v13zm8 0v-7h8v7" fill="white" opacity=".95"/>
    </svg>`;
    return {
        url: "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg),
        scaledSize: new google.maps.Size(52,52),
        anchor: new google.maps.Point(26,26)
    };
}

function focusStoreCard(storeId){
    document.querySelectorAll(".store-card").forEach(card => card.classList.remove("active-store"));
    const box = document.querySelector(`.store-box[data-store-id="${storeId}"]`);
    if(box){
        box.checked = true;
        if(!selectedOrder.includes(storeId)){
            selectedOrder.push(storeId);
        }
        updateTotals();
        const card = box.closest(".store-card");
        if(card){
            card.classList.add("active-store");
            card.scrollIntoView({behavior:"smooth", block:"center"});
        }
    }
}

function selectStoreFromMap(storeId){
    focusStoreCard(storeId);
    if(activeClusterInfo) activeClusterInfo.close();
    previewRoute();
}
window.selectStoreFromMap = selectStoreFromMap;


function visibleUnassignedStores(){ return stores.filter(s => s.status === "Unassigned"); }

function selectedIds(){
    return [...document.querySelectorAll(".store-box:checked")].map(b => b.dataset.storeId);
}

function updateSelectionOrder(){
    const ids = selectedIds();
    ids.forEach(id => { if(!selectedOrder.includes(id)) selectedOrder.push(id); });
    selectedOrder = selectedOrder.filter(id => ids.includes(id));
}


function selectAllVisible(){
    document.querySelectorAll(".store-box").forEach(box => { box.checked = true; if(!selectedOrder.includes(box.dataset.storeId)) selectedOrder.push(box.dataset.storeId); });
    updateTotals();
}
function clearSelection(){
    document.querySelectorAll(".store-box").forEach(box => box.checked = false);
    selectedOrder = [];
    updateTotals();
}
function selectDueToday(){
    const today = new Date(); today.setHours(0,0,0,0);
    document.querySelectorAll(".store-box").forEach(box => {
        const store = stores.find(s => s.id === box.dataset.storeId);
        const due = store ? parseDueDate(store.due_date) : null;
        if(due){ due.setHours(0,0,0,0); }
        const shouldSelect = due && due <= today;
        box.checked = !!shouldSelect;
        if(shouldSelect && !selectedOrder.includes(box.dataset.storeId)) selectedOrder.push(box.dataset.storeId);
    });
    selectedOrder = selectedOrder.filter(id => Array.from(document.querySelectorAll(".store-box:checked")).some(b => b.dataset.storeId === id));
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
            option.textContent = (driver.name || driver.username) + (driver.cities && driver.cities.length ? " — " + driver.cities.join(", ") : "");
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
                <span>BOL ${store.bol || ""} • Origin ${store.origin || ""}</span>
                <span>${store.city || ""}, ${store.state || ""} • ${store.expected_racks || 0} racks</span>
                <span>${store.due_date ? "Due: " + store.due_date : "Due: Not captured"} • <b class="due-${dueStatus(store)}">${dueStatus(store).toUpperCase()}</b></span>
                <small>${store.hub || "Manual Review"}</small><br><a class="mini-link" href="/bol-live/${store.bol}" target="_blank" onclick="event.stopPropagation()">Live BOL</a> <a class="mini-link" href="/bol-view/${store.id}" target="_blank" onclick="event.stopPropagation()">Saved Copy</a> <a class="mini-link" href="/bol-print/${store.id}" target="_blank" onclick="event.stopPropagation()">Print</a>
            </div>
        `;
        container.appendChild(label);
    });
}

function updateTotals(){
    updateSelectionOrder();
    let count = 0, racks = 0, weight = 0;

    document.querySelectorAll(".store-box:checked").forEach(box => {
        count++;
        racks += Number(box.dataset.racks || 0);
        weight += Number(box.dataset.weight || 0);
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
            return store ? `<div class="preview-stop"><b>${index + 1}</b> ${store.store_name || store.origin || "Store"}<small>BOL ${store.bol || ""} &middot; ${Number(store.weight || 0).toLocaleString()} lbs</small></div>` : "";
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
        html += `<div class="preview-stop">${index + 1}. ${s.store_name || s.origin} — ${s.city}, ${s.state} — BOL ${s.bol || ""}</div>`;
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

        if(markers[storeId]) markers[storeId].setMap(map);

        row.remove();
        renderStores();
        updateTotals();
    }
}

function initMap(){
    if(!window.google || !google.maps){
        const el = document.getElementById("map");
        if(el) el.innerHTML = "<div class='map-missing-key'><b>Google Maps did not load.</b><br>The store list and route builder still work locally.</div>";
        renderStores();
        updateTotals();
        if (typeof renderMapDispatchBoard === "function") renderMapDispatchBoard();
        return;
    }
    map = new google.maps.Map(document.getElementById("map"), {
        zoom: 6,
        center: {lat: 30.8, lng: -97.2},
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: true,
        gestureHandling: "greedy",
        styles: [
            {elementType:"geometry", stylers:[{color:"#17212b"}]},
            {elementType:"labels.text.stroke", stylers:[{color:"#111820"}]},
            {elementType:"labels.text.fill", stylers:[{color:"#e7e7e7"}]},
            {featureType:"water", elementType:"geometry", stylers:[{color:"#0c3357"}]},
            {featureType:"road", elementType:"geometry", stylers:[{color:"#2b333b"}]},
            {featureType:"poi", stylers:[{visibility:"off"}]}
        ]
    });

    const bounds = new google.maps.LatLngBounds();

    Object.keys(hubs).forEach(hubName => {
        const hub = hubs[hubName];
        const hubPos = {lat: Number(hub.lat), lng: Number(hub.lng)};
        const marker = new google.maps.Marker({
            position: hubPos,
            map,
            title: hubName + " Hub",
            icon: hubIcon()
        });
        const info = new google.maps.InfoWindow({
            content: `<div style="font-family:Arial"><b>${hubName.toUpperCase()} HUB</b><br>${hub.address || ""}</div>`
        });
        marker.addListener("click", () => info.open(map, marker));
        bounds.extend(hubPos);
    });

    let pinNumber = 1;

    stores.forEach(store => {
        if(store.status !== "Unassigned") return;

        let lat = Number(store.lat);
        let lng = Number(store.lng);
        if(!lat || !lng || isNaN(lat) || isNaN(lng)) return;

        const pos = {lat: lat, lng: lng};
        const thisPinNumber = pinNumber++;
        const color = dueStatus(store);

        markers[store.id] = new google.maps.Marker({
            position: pos,
            map,
            title: `${thisPinNumber}. BOL ${store.bol || ""} • Due ${store.due_date || "Not captured"} • ${color.toUpperCase()}`,
            icon: pinIcon(thisPinNumber, color)
        });

        bounds.extend(pos);
        markers[store.id].addListener("click", () => focusStoreCard(store.id));
    });

    renderStores();

    const visibleMarkers = Object.keys(markers).length;
    if(visibleMarkers > 0){
        map.fitBounds(bounds);
        if(visibleMarkers === 1){
            map.setZoom(10);
        }
    }
}


function getSelectedStoreIds(){
    const checked = Array.from(document.querySelectorAll(".store-box:checked")).map(x => x.dataset.storeId);
    const ordered = selectedOrder.filter(id => checked.includes(id));
    checked.forEach(id => {
        if(!ordered.includes(id)) ordered.push(id);
    });
    return ordered;
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
                    <div class="map-board-sub">${store.city || ""}, ${store.state || ""} • ${store.expected_racks || 0} racks • ${store.weight || 0} lbs</div>
                    ${store.assigned_driver ? `<div class="map-board-driver">Driver: <b>${store.assigned_driver}</b></div>` : ""}
                    <div class="map-board-actions">
                        <a class="mini-link" href="/bol-live/${store.bol}" target="_blank">Live</a>
                        <a class="mini-link" href="/bol-view/${store.id}" target="_blank">Saved</a>
                        <a class="mini-link" href="/bol-print/${store.id}" target="_blank">Print</a>
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
                        <div class="map-board-sub">${store.city || ""}, ${store.state || ""} • ${store.expected_racks || 0} racks • ${store.weight || 0} lbs</div>
                        ${store.assigned_driver ? `<div class="map-board-driver">Driver: <b>${store.assigned_driver}</b></div>` : ""}
                        <div class="map-board-actions">
                            <a class="mini-link" href="/bol-live/${store.bol}" target="_blank">Live</a>
                            <a class="mini-link" href="/bol-view/${store.id}" target="_blank">Saved</a>
                            <a class="mini-link" href="/bol-print/${store.id}" target="_blank">Print</a>
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
    loadDrivers();
});



// Local fallback: render the store list/board even if Google Maps does not load.
document.addEventListener("DOMContentLoaded", function(){
    try {
        if (document.getElementById("available-stores")) {
            renderStores();
            updateTotals();
        }
        if (typeof renderMapDispatchBoardLive === "function") {
            renderMapDispatchBoardLive();
        }
        setTimeout(function(){
            var mapBox = document.getElementById("map");
            if (mapBox && !map) {
                if (!mapBox.innerHTML.trim()) {
                    mapBox.innerHTML = "<div class='map-missing-key'>Map did not load locally. Check Settings for Google Maps API key, then click Fix / Reload Pins.</div>";
                }
            }
        }, 2500);
    } catch (err) {
        console.error("Dispatch Map local fallback failed:", err);
    }
});

window.initMap = initMap;
