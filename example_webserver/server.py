WAIT_FOR_START_COMMAND = False

if __name__ == '__main__':
    server = "0.0.0.0"
    port = 5025

    print (f"STT speech to text server")
    print (f"runs on http://{server}:{port}")
    print ()
    print ("starting")
    print ("└─ ... ", end='', flush=True)

    from RealtimeSTT import AudioToTextRecorder
    from colorama import Fore, Style
    import websockets
    import threading
    import colorama
    import asyncio
    import shutil
    import queue
    import json
    import time
    import os

    colorama.init()

    # Global variables for session management
    accumulated_text = ""
    session_active = False
    session_start_time = 0
    last_speech_time = 0
    SESSION_DURATION = 30  # 20 seconds
    SILENCE_INTERVAL = 2   # 2 seconds

    first_chunk = True
    full_sentences = []
    displayed_text = ""
    message_queue = queue.Queue()
    start_recording_event = threading.Event()
    start_transcription_event = threading.Event()
    connected_clients = set()

    def clear_console():
        os.system('clear' if os.name == 'posix' else 'cls')

    async def handler(websocket):
        print ("\r└─ Client connected")
        if WAIT_FOR_START_COMMAND:
            print("waiting for start command")
            print ("└─ ... ", end='', flush=True)

        connected_clients.add(websocket)

        try:
            async for message in websocket:
                data = json.loads(message)
                if data.get("type") == "command" and data.get("content") == "start-recording":
                    print ("\r└─ OK")
                    start_recording_event.set()

        except json.JSONDecodeError:
            print (Fore.RED + "STT Received an invalid JSON message." + Style.RESET_ALL)
        except websockets.ConnectionClosedError:
            print (Fore.RED + "connection closed unexpectedly by the client" + Style.RESET_ALL)
        except websockets.exceptions.ConnectionClosedOK:
            print("connection closed.")
        finally:
            print("client disconnected")
            connected_clients.discard(websocket)
            print ("waiting for clients")
            print ("└─ ... ", end='', flush=True)


    def add_message_to_queue(type: str, content):
        message = {
            "type": type,
            "content": content
        }
        message_queue.put(message)

    def fill_cli_line(text):
        columns, _ = shutil.get_terminal_size()
        return text.ljust(columns)[-columns:]

    def text_detected(text):
        global displayed_text, first_chunk, accumulated_text, last_speech_time, session_active

        if session_active and text and text != displayed_text:
            # Update last speech time
            last_speech_time = time.time()

            # Auto-confirm previous realtime text if exists
            if displayed_text and displayed_text not in accumulated_text:
                accumulated_text += " " + displayed_text
                print(f"\n[DEBUG] Auto-confirmed: '{displayed_text}'")

            # Set new realtime text
            displayed_text = text
            first_chunk = False
            add_message_to_queue("realtime", text)

            # Display: accumulated_text + current realtime text
            full_display = accumulated_text + " " + text if accumulated_text else text
            message = fill_cli_line(full_display)
            message = "└─ " + Fore.CYAN + message[:-3] + Style.RESET_ALL
            print(f"\r{message}", end='', flush=True)

    def start_session():
        global session_active, session_start_time, last_speech_time, accumulated_text, displayed_text

        # End previous session if active
        if session_active:
            end_session()
            time.sleep(0.5)  # Brief pause

        print("\n🚀 Starting new session (20 seconds)...")
        print("Press 1 again to start new session anytime")
        print("-" * 50)

        # RESET everything completely
        accumulated_text = ""
        displayed_text = ""
        session_active = True
        session_start_time = time.time()
        last_speech_time = time.time()  # Important: reset this to current time

        # Clear the message queue
        while not message_queue.empty():
            message_queue.get()

        # Display empty line ready for text
        print("└─ ", end='', flush=True)

    def end_session():
        global session_active, accumulated_text, displayed_text

        if session_active:
            # Auto-confirm any remaining realtime text
            if displayed_text and displayed_text not in accumulated_text:
                accumulated_text += " " + displayed_text
                print(f"\n[DEBUG] Final confirm: '{displayed_text}'")

            session_active = False
            print(f"\n\n{'='*60}")
            print("📝 FINAL ACCUMULATED TEXT:")
            print(f"{'='*60}")
            print(accumulated_text.strip() if accumulated_text.strip() else "(No speech detected)")
            print(f"{'='*60}")
            print("Session ended. Press 1 to start new session.")

    def silence_monitor():
        """Monitor for silence and add tokens every 2 seconds"""
        global accumulated_text, last_speech_time, session_active, displayed_text

        while True:
            if session_active:
                current_time = time.time()

                # Check if session should end (20 seconds)
                if current_time - session_start_time >= SESSION_DURATION:
                    end_session()
                    continue

                # Check for silence (2 seconds without speech)
                if current_time - last_speech_time >= SILENCE_INTERVAL:
                    # Add silence token
                    accumulated_text += " <silence>"
                    last_speech_time = current_time

                    # Update display
                    full_display = accumulated_text + displayed_text
                    message = fill_cli_line(full_display)
                    message = "└─ " + Fore.CYAN + message[:-3] + Style.RESET_ALL
                    print(f"\r{message}", end='', flush=True)

            time.sleep(0.5)  # Check every 0.5 seconds

    # Start silence monitor thread
    silence_thread = threading.Thread(target=silence_monitor, daemon=True)
    silence_thread.start()


    async def broadcast(message_obj):
        if connected_clients:
            for client in connected_clients:
                await client.send(json.dumps(message_obj))

    async def send_handler():
        while True:
            while not message_queue.empty():
                message = message_queue.get()
                await broadcast(message)
            await asyncio.sleep(0.02)

    def recording_started():
        # Silent - no print
        add_message_to_queue("record_start", "")

    def recording_stopped():
        """Called when recording stops - confirm current realtime text"""
        global displayed_text, accumulated_text, session_active, last_speech_time

        if session_active and displayed_text.strip():
            # Confirm the current realtime text
            if accumulated_text and not accumulated_text.endswith(' '):
                accumulated_text += " " + displayed_text.strip()
            else:
                accumulated_text += displayed_text.strip()

            displayed_text = ""  # Clear realtime text
            last_speech_time = time.time()  # Update speech time

            # Update display with confirmed text
            message = fill_cli_line(accumulated_text)
            message = "└─ " + Fore.YELLOW + message[:-3] + Style.RESET_ALL
            print(f"\r{message}", end='', flush=True)

    def vad_detect_started():
        # Silent - no print
        add_message_to_queue("vad_start", "")

    def wakeword_detect_started():
        add_message_to_queue("wakeword_start", "")

    def transcription_started():
        add_message_to_queue("transcript_start", "")

    recorder_config = {
        'spinner': False,
        'use_microphone': True,
        'model': 'small.en',
        'language': 'en',
        'silero_sensitivity': 0.3,   # Tăng từ 0.1 lên 0.3 để ít nhạy cảm hơn
        'webrtc_sensitivity': 2,     # Tăng lại từ 1 lên 2
        'silero_use_onnx': False,
        'post_speech_silence_duration': 2.0,  # Tăng từ 1.0 lên 2.0 giây
        'min_length_of_recording': 0.5,       # Tăng từ 0.1 lên 0.5 giây
        'min_gap_between_recordings': 0.3,    # Thêm gap 0.3 giây
        'enable_realtime_transcription': True,
        'realtime_processing_pause': 0.1,     # Thêm pause 0.1 giây
        'realtime_model_type': 'tiny.en',
        'on_realtime_transcription_stabilized': text_detected,
        'on_recording_start': recording_started,
        'on_recording_stop': recording_stopped,  # Add this callback
        'on_vad_detect_start': vad_detect_started,
        'on_wakeword_detection_start': wakeword_detect_started,
        'on_transcription_start': transcription_started,
    }

    recorder = AudioToTextRecorder(**recorder_config)

    def transcriber_thread():
        global accumulated_text, displayed_text, session_active, last_speech_time

        while True:
            start_transcription_event.wait()

            if session_active:
                # Get final sentence from recorder
                sentence = recorder.transcribe()

                if sentence and sentence.strip():
                    # Update last speech time when we get confirmed text
                    last_speech_time = time.time()

                    # Add confirmed sentence to accumulated text with space
                    if accumulated_text and not accumulated_text.endswith(' '):
                        accumulated_text += " " + sentence.strip()
                    else:
                        accumulated_text += sentence.strip()

                    displayed_text = ""  # Clear realtime text since it's now confirmed

                    # Display updated accumulated text
                    message = fill_cli_line(accumulated_text)
                    message = "└─ " + Fore.YELLOW + message[:-3] + Style.RESET_ALL
                    print(f"\r{message}", end='', flush=True)

                    add_message_to_queue("full", accumulated_text)

            start_transcription_event.clear()

    def input_handler():
        """Handle user input for starting sessions"""
        while True:
            try:
                user_input = input().strip()
                if user_input == "1":
                    start_session()
            except:
                pass

    def recorder_thread():
        global first_chunk, session_active
        while True:
            if not session_active:
                time.sleep(0.1)
                continue

            if not len(connected_clients) > 0:
                time.sleep(0.1)
                continue

            first_chunk = True
            if WAIT_FOR_START_COMMAND:
                start_recording_event.wait()

            recorder.wait_audio()
            start_transcription_event.set()
            start_recording_event.clear()

    # Start all threads
    threading.Thread(target=recorder_thread, daemon=True).start()
    threading.Thread(target=transcriber_thread, daemon=True).start()
    threading.Thread(target=input_handler, daemon=True).start()

    print ("\r└─ OK")
    print("🎙️ Speech-to-Text Server Ready!")
    print("📝 Press '1' + Enter to start a 20-second session")
    print("🔄 Press '1' again anytime to restart session")
    print("⏰ Sessions auto-end after 20 seconds")
    print("-" * 50)

    try:
        # Chạy WebSocket server trong async context
        async def main():
            start_server = websockets.serve(handler, server, port)
            await start_server
            await send_handler()

        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        if recorder:
            try:
                recorder.stop()
                recorder.shutdown()
                print("Recorder cleaned up successfully")
            except:
                pass