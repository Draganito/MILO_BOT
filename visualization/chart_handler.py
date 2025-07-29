# src/visualization/chart_handler.py
import http.server
import socketserver
import threading
import webbrowser
import json as json_module
from typing import Optional
from analysis.script_engine import ScriptEngine

class ChartHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, script_engine: Optional[ScriptEngine] = None, **kwargs) -> None:
        self.script_engine = script_engine
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Bot Chart Visualization</title>
<script src="/chart.js"></script>
</head>
<body style="margin:0; overflow:hidden;">
<canvas id="chartCanvas"></canvas>
<script>
const chart = new CandleChart('chartCanvas');
function updateChart() {
  fetch('/data')
  .then(response => response.json())
  .then(data => {
    data.historical.forEach(c => c.time = new Date(c.time));
    if (data.liveCandle) data.liveCandle.time = new Date(data.liveCandle.time);
    chart.setData(data.historical, data.liveCandle, data.zigzag, data.divergences);
  })
  .catch(error => console.error('Error fetching data:', error));
}
updateChart();
setInterval(updateChart, 5000);
</script>
</body>
</html>
"""
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/data':
            if self.script_engine:
                data = self.script_engine.get_chart_data_for_js()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json_module.dumps(data, default=str).encode('utf-8'))
            else:
                self.send_error(500, "No data available")
        else:
            super().do_GET()