let map;
let markers = {};
const stores = window.EOMS_STORES || [];
const hubs = window.EOMS_HUBS || {};
const MAX_CAPACITY = window.MAX_PAYLOAD || 25001;
let selectedOrder = [];

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
    if(diffDays < 0) return "red";
    if(diffDays <= 4) return "amber";
    return "green";
}

function pinIcon(number, color){
    const colors = {
        green: "#22c55e",
        amber: "#f59e0b",
        red: "#ef4444"
    };
    const fill = colors[color] || colors.green;
    const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="38" height="46" viewBox="0 0 38 46">
      <path d="M19 45C19 45 36 27 36 17C36 7.6 28.4 0 19 0C9.6 0 2 7.6 2 17C2 27 19 45 19 45Z" fill="${fill}" stroke="white" stroke-width="3"/>
      <circle cx="19" cy="17" r="11" fill="rgba(0,0,0,.22)"/>
      <text x="19" y="22" text-anchor="middle" font-family="Arial" font-size="13" font-weight="900" fill="white">${number}</text>
    </svg>`;
    return {
        url: "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg),
        scaledSize: new google.maps.Size(38,46),
        anchor: new google.maps.Point(19,46)
    };
}

function focusStoreCard(storeId){
    document.querySelectorAll(".store-card").forEach(card => card.classList.remove("active-store"));
    const box = document.querySelector(`.store-box[data-store-id="${storeId}"]`);
    if(box){
        box.checked = true;
        updateTotals();
        const card = box.closest(".store-card");
        if(card){
            card.classList.add("active-store");
            card.scrollIntoView({behavior:"smooth", block:"center"});
        }
    }
}


function visibleUnassignedStores(){ return stores.filter(s => s.status === "Unassigned"); }

function selectedIds(){
    return [...document.querySelectorAll(".store-box:checked")].map(b => b.dataset.storeId);
}

function updateSelectionOrder(){
    const ids = selectedIds();
    ids.forEach(id => { if(!selectedOrder.includes(id)) selectedOrder.push(id); });
    selectedOrder = selectedOrder.filter(id => ids.includes(id));
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
                <small>${store.hub || "Manual Review"}</small><br><a class="mini-link" href="/bol-live/${store.bol}" target="_blank" onclick="event.stopPropagation()">Live BOL</a> <a class="mini-link" href="/bol-view/${store.id}" target="_blank" onclick="event.stopPropagation()">Saved Copy</a>
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
            <p><b>Revenue:</b> $${m.revenue}</p>
            <p><b>Driver Pay:</b> $${m.driver_pay}</p>
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

    const response = await fetch("/api/assign-route", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({driver: driver, store_ids: ids, mode: mode})
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
        <p><b>Revenue:</b> $${route.metrics.revenue}</p>
        <p><b>Driver Pay:</b> $${route.metrics.driver_pay}</p>
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

        if(markers[store.id]) markers[store.id].setMap(null);

        const original = stores.find(s => s.id === store.id);
        if(original){
            original.status = "Assigned";
            original.assigned_driver = driver;
        }
    });

    document.getElementById("driver-results").appendChild(routeBlock);
    selectedOrder = [];
    renderStores();
    updateTotals();
    document.getElementById("route-preview").innerHTML = "<p class='muted'>Route assigned. View full route in Route Builder.</p>";
}

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
    map = new google.maps.Map(document.getElementById("map"), {
        zoom: 6,
        center: {lat: 30.2672, lng: -97.7431},
        mapTypeControl: false,
        streetViewControl: false
    });

    const bounds = new google.maps.LatLngBounds();

    Object.keys(hubs).forEach(hubName => {
        const hub = hubs[hubName];
        const hubPos = {lat: Number(hub.lat), lng: Number(hub.lng)};
        new google.maps.Marker({
            position: hubPos,
            map,
            title: hubName + " Hub",
            label: "H"
        });
        bounds.extend(hubPos);
    });

    const coordCount = {};
    let pinNumber = 1;

    stores.forEach(store => {
        if(store.status !== "Unassigned") return;

        let lat = Number(store.lat);
        let lng = Number(store.lng);

        if(!lat || !lng || isNaN(lat) || isNaN(lng)) return;

        const key = lat.toFixed(4) + "," + lng.toFixed(4);
        coordCount[key] = (coordCount[key] || 0) + 1;

        const offsetIndex = coordCount[key] - 1;
        const offset = offsetIndex * 0.018;

        const pos = {
            lat: lat + offset,
            lng: lng + offset
        };

        const thisPinNumber = pinNumber++;
        const color = dueStatus(store);

        markers[store.id] = new google.maps.Marker({
            position: pos,
            map,
            title: `${thisPinNumber}. BOL ${store.bol || ""} ${store.store_name || store.origin || "Store"}`,
            icon: pinIcon(thisPinNumber, color)
        });

        bounds.extend(pos);

        markers[store.id].addListener("click", () => {
            focusStoreCard(store.id);
        });
    });

    renderStores();

    const visibleMarkers = Object.keys(markers).length;
    if(visibleMarkers > 0){
        map.fitBounds(bounds);
        if(visibleMarkers === 1){
            map.setZoom(8);
        }
    }
}
