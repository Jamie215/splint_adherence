// Heartbeat: while this tab is open, tell the server every 5 seconds that the
// interface is still in use. The server shuts itself down after 5 minutes
// without one (see app.py) and warns this tab first, which then shows the
// timeout page.
var heartbeatInterval;

window.addEventListener("load", function () {
    var socket = io();

    socket.on("connect", function () {
        clearInterval(heartbeatInterval);
        heartbeatInterval = setInterval(function () {
            navigator.sendBeacon("/heartbeat");
        }, 5000);
    });

    socket.on("disconnect", function () {
        clearInterval(heartbeatInterval);
    });

    socket.on("server_shutdown_warning", function () {
        window.location.href = "/timeout";
    });
});
