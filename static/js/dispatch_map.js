let map;
let markers = {};
const stores = window.EOMS_STORES || [];
const hubs = window.EOMS_HUBS || {};
const MAX_CAPACITY = window.MAX_PAYLOAD || 25001;

function visibleUnassignedStores(){ return stores.filter(s => s.status === "Unassigned"); }

function renderStores(){
    const container = document.getElementById("available-stores");
    container.innerHTML = "";
    const available = visibleUnassignedStores();

    if(available.length === 0){
        container.innerHTML = "<p class='muted'>No unassigned stores. Import RMS PDFs or approve Need Review items.</p>";
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
                <span>BOL ${store.bol || ""} • ${store.city || ""}, ${store.state || ""} • ${store.expected_racks || 0} racks</span>
                <small>${store.hub || "Manual Review"} — ${store.hub_reason || ""}</small>
            </div>
        `;
        container.appendChild(label);
    });
}

function updateTotals(){
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

async function assignDriver(){
    const driver = document.getElementById("driver-select").value;
    if(!driver){ alert("Select a driver"); return; }

    const selectedBoxes = [...document.querySelectorAll(".store-box:checked")];
    if(selectedBoxes.length === 0){ alert("Select stores first"); return; }

    const storeIds = selectedBoxes.map(box => box.dataset.storeId);
    const response = await fetch("/api/assign-route", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({driver:driver, store_ids:storeIds})
    });
    const data = await response.json();
    if(!data.ok){ alert("Assignment failed"); return; }

    const routeBlock = document.createElement("div");
    routeBlock.className = "route-card";
    routeBlock.innerHTML = `<h4>${driver}</h4>`;

    data.assigned.forEach(store => {
        const row = document.createElement("div");
        row.className = "route-row";
        row.innerHTML = `<span>${store.store_name || store.origin} <small>BOL ${store.bol || ""}</small></span>`;

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
    renderStores();
    updateTotals();
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
        zoom:6,
        center:{lat:30.2672,lng:-97.7431},
        mapTypeControl:false,
        streetViewControl:false
    });

    Object.keys(hubs).forEach(hubName => {
        const hub = hubs[hubName];
        new google.maps.Marker({position:{lat:hub.lat,lng:hub.lng}, map, title:hubName + " Hub", label:"H"});
    });

    stores.forEach(store => {
        if(store.status !== "Unassigned") return;
        markers[store.id] = new google.maps.Marker({
            position:{lat:Number(store.lat),lng:Number(store.lng)},
            map,
            title:store.store_name || store.origin || "Store",
            label:"S"
        });
    });

    renderStores();
}
