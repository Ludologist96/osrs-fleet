from flask import Flask, jsonify, request, send_file, Response
from flask_cors import CORS
import time
import io
import threading
from core.control import ScriptControl
from core.logger import get_logger
from core import cv_debug

class BotAPI:
    def __init__(self, client=None):
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for all routes
        self.control = ScriptControl()
        self.client = client  # Reference to RuneLiteClient instance
        self.log = get_logger("API")
        self.start_time = time.time()
        self.thread = None
        
        # Define routes
        self.register_routes()
        
    def register_routes(self):
        # Status endpoints
        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            return jsonify({
                'running': not self.control.terminate,
                'paused': self.control.pause,
                'runtime': time.time() - self.start_time
            })
        
        # Control endpoints
        @self.app.route('/api/control/terminate', methods=['GET'])
        def get_terminate():
            return jsonify({'terminate': self.control.terminate})
            
        @self.app.route('/api/control/terminate', methods=['POST'])
        def set_terminate():
            value = request.json.get('terminate', False)
            self.control.terminate = bool(value)
            return jsonify({'terminate': self.control.terminate})
        
        @self.app.route('/api/control/pause', methods=['GET'])
        def get_pause():
            return jsonify({'pause': self.control.pause})
            
        @self.app.route('/api/control/pause', methods=['POST'])
        def set_pause():
            value = request.json.get('pause', False)
            self.control.pause = bool(value)
            return jsonify({'pause': self.control.pause})
        
        # Screenshot endpoint
        @self.app.route('/api/screenshot', methods=['GET'])
        def get_screenshot():
            if not self.client:
                return jsonify({'error': 'Client not available'}), 503
                
            try:
                screenshot = self.client.get_screenshot()
                img_io = io.BytesIO()
                screenshot.save(img_io, 'PNG')
                img_io.seek(0)
                return send_file(img_io, mimetype='image/png')
            except Exception as e:
                self.log.error(f"Screenshot error: {str(e)}")
                return jsonify({'error': str(e)}), 500
        
        # Runtime endpoint
        @self.app.route('/api/runtime', methods=['GET'])
        def get_runtime():
            runtime_seconds = time.time() - self.start_time
            hours, remainder = divmod(runtime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            return jsonify({
                'runtime_seconds': runtime_seconds,
                'formatted': f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}",
                'started_at': self.start_time
            })
        
        # CV Debug endpoint - proxy to cv_debug server
        @self.app.route('/debug')
        def debug_index():
            """Serve the CV debug interface"""
            try:
                # Get the debug port (should already be enabled in bot.py)
                debug_port = getattr(self, '_debug_port', 5555)
                
                # Return a simple redirect/proxy page
                debug_port = getattr(self, '_debug_port', 5555)
                return f'''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>CV Debug</title>
                    <style>
                        body {{ margin: 0; padding: 0; background: #111; color: #eee; font-family: sans-serif; }}
                        .loading {{ text-align: center; padding: 50px; }}
                        iframe {{ width: 100%; height: 100vh; border: none; }}
                    </style>
                </head>
                <body>
                    <div class="loading" id="loading">Loading CV Debug...</div>
                    <iframe id="debug-frame" src="http://localhost:{debug_port}" style="display: none;"></iframe>
                    <script>
                        const iframe = document.getElementById('debug-frame');
                        const loading = document.getElementById('loading');
                        
                        iframe.onload = function() {{
                            loading.style.display = 'none';
                            iframe.style.display = 'block';
                        }};
                        
                        iframe.onerror = function() {{
                            loading.innerHTML = 'CV Debug not available. Make sure the bot is running.';
                        }};
                        
                        // Show iframe after a short delay even if onload doesn't fire
                        setTimeout(() => {{
                            loading.style.display = 'none';
                            iframe.style.display = 'block';
                        }}, 3000);
                    </script>
                </body>
                </html>
                '''
            except Exception as e:
                self.log.error(f"CV Debug error: {e}")
                return f'''
                <html>
                <body style="background: #111; color: #eee; font-family: sans-serif; padding: 50px; text-align: center;">
                    <h2>CV Debug Unavailable</h2>
                    <p>Error: {str(e)}</p>
                    <p>Make sure the bot is properly initialized.</p>
                </body>
                </html>
                ''', 503
    
    def start(self, port=5432):
        """Start the API server in a background thread"""
        if self.thread and self.thread.is_alive():
            self.log.warning("API server is already running")
            return
        
        # Store the port for cv_debug use
        self._api_port = port
            
        def run_server():
            self.log.info(f"Starting API server on port {port}")
            self.app.run(host='0.0.0.0', port=port, threaded=True)
            
        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        
    def stop(self):
        """Stop the API server (if running)"""
        # Note: Flask doesn't provide a clean way to stop from another thread
        self.log.info("API shutdown requested - server will stop when process terminates")


# Function to create and configure a BotAPI instance
def create_bot_api(client=None):
    return BotAPI(client)
