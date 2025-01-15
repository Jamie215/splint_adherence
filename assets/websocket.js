function logToServer(message) {
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/log", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.send(JSON.stringify({ message: message }));
}

var socket;
var heartbeatInterval;
var heartbeatTimeout;

function logMessage(message) {
    let logs = localStorage.getItem("logMessages") || "";
    logs += message + "\n";
    localStorage.setItem("logMessages", logs);
    console.log(message);
}

window.onload = function() {
    var logs = localStorage.getItem("logMessages");
    if (logs) {
        console.log("Stored logs: " + logs);
        console.log(logs);
        localStorage.removeItem("logMessages");
    }

    socket = io();
    logMessage("Socket initialized");

    socket.on("connect", () => {
        logMessage("Socket connected");

        // Start sending heartbeat signals every 5 seconds
        heartbeatInterval = setInterval(() => {
            logMessage("Sending heartbeat");
            navigator.sendBeacon("/heartbeat");
        }, 5000);
    });

    socket.on("server_shutdown_warning", function() {
        logMessage("Received server shutdown warning");
        window.location.href = "/timeout";
    });

    socket.on("disconnect", () => {
        logMessage("Socket disconnected");
        clearInterval(heartbeatInterval);
    });
    
    // Set flag before unload
    window.addEventListener("beforeunload", (event) => {
        navigator.sendBeacon("/heartbeat");
    });
};