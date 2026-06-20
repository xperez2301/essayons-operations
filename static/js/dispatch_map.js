const MAX_CAPACITY = 25001;
let map;
let markers = {};

const storeLocations = {
    "Walmart #1001": { lat: 30.0802, lng: -94.1266 },
    "Home Depot #2001": { lat: 31.1171, lng: -97.7278 },
    "Lowe's #3001": { lat: 29.8833, lng: -97.9414 }
};

function updateTotals(){
    let stores = 0;
    let racks = 0;
    let weight = 0;

    document.querySelectorAll(".store-box").forEach(box => {
        if(box.checked && box.closest(".store-card").style.display !== "none"){
            stores++;
            racks += Number(box.dataset.racks);
            weight += Number(box.dataset.weight);
        }
    });

    document.getElementById("store-count").innerText = stores;
    document.getElementById("rack-count").innerText = racks;
    document.getElementById("weight-count").innerText = weight;
    document.getElementById("remaining-capacity").innerText = MAX_CAPACITY - weight;

    const status = document.getElementById("capacity-status");
    status.className = "";

    if(weight > MAX_CAPACITY){
        status.innerText = "OVER LIMIT";
        status.classList.add("over");
    } else if(weight > 22000){
        status.innerText = "WARNING";
        status.classList.add("warning");
    } else {
        status.innerText = "SAFE";
        status.classList.add("safe");
    }
}

document.addEventListener("change", updateTotals);

function assignDriver(){
    const driver = document.getElementById("driver-select").value;
    if(!driver){ alert("Select a driver"); return; }

    const selected = document.querySelectorAll(".store-box:checked");
    if(selected.length === 0){ alert("Select stores first"); return; }

    const routeBlock = document.createElement("div");
    routeBlock.className = "route-card";
    routeBlock.innerHTML = `<h4>${driver}</h4>`;

    selected.forEach(box => {
        const card = box.closest(".store-card");
        const store = card.querySelector("strong").innerText.trim();

        const row = document.createElement("div");
        row.className = "route-row";
        row.innerHTML = `<span>${store}</span>`;

        const btn = document.createElement("button");
        btn.innerText = "Unassign";
        btn.onclick = function(){
            card.style.display = "flex";
            if(markers[store]) markers[store].setMap(map);
            row.remove();
            updateTotals();
        };

        row.appendChild(btn);
        routeBlock.appendChild(row);

        card.style.display = "none";
        box.checked = false;
        if(markers[store]) markers[store].setMap(null);
    });

    document.getElementById("driver-results").appendChild(routeBlock);
    updateTotals();
}

function initMap(){
    map = new google.maps.Map(document.getElementById("map"), {
        zoom: 6,
        center: { lat: 30.2672, lng: -97.7431 },
        mapTypeControl: false,
        streetViewControl: false
    });

    const hubs = [
        { lat:29.4241, lng:-98.4936, title:"San Antonio Hub" },
        { lat:29.7604, lng:-95.3698, title:"Houston Hub" },
        { lat:32.7767, lng:-96.7970, title:"Dallas Hub" }
    ];

    hubs.forEach(hub => {
        new google.maps.Marker({
            position: { lat:hub.lat, lng:hub.lng },
            map,
            title: hub.title,
            label: "H"
        });
    });

    Object.keys(storeLocations).forEach(store => {
        const loc = storeLocations[store];
        markers[store] = new google.maps.Marker({
            position: { lat:loc.lat, lng:loc.lng },
            map,
            title: store,
            label: "S"
        });
    });
}
