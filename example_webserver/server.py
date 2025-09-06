WAIT_FOR_START_COMMAND = False

if __name__ == '__main__':
    server = "localhost"
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

    # Text tích lũy từ đầu đến cuối chương trình
    complete_session_text = ""
    silence_timer = None
    is_currently_speaking = False

    def add_silence_token():
        global complete_session_text, silence_timer
        if not is_currently_speaking:  # Chỉ thêm khi không đang nói
            complete_session_text += " <silence>"
            print(f"\r{complete_session_text}", end='', flush=True)
            add_message_to_queue("realtime", complete_session_text)

            # Lên lịch silence token tiếp theo sau 2 giây
            silence_timer = threading.Timer(2.0, add_silence_token)
            silence_timer.start()

    def text_detected(text):
        global complete_session_text, silence_timer, is_currently_speaking

        is_currently_speaking = True

        # Hủy silence timer khi có voice
        if silence_timer:
            silence_timer.cancel()
            silence_timer = None

        # Cập nhật text - thay thế từ cuối với text mới (realtime)
        if text:
            # Tìm vị trí của silence token cuối cùng
            last_silence_pos = complete_session_text.rfind("<silence>")
            if last_silence_pos != -1:
                # Có silence token, thêm text sau silence token cuối
                complete_session_text = complete_session_text[:last_silence_pos + 9] + " " + text
            else:
                # Không có silence token, thêm vào cuối
                if complete_session_text and not complete_session_text.endswith(" "):
                    complete_session_text += " " + text
                else:
                    complete_session_text += text

            print(f"\r{complete_session_text}", end='', flush=True)
            add_message_to_queue("realtime", complete_session_text)

    def recording_started():
        global is_currently_speaking
        is_currently_speaking = True

    def vad_detect_started():
        global silence_timer, is_currently_speaking
        is_currently_speaking = True
        if silence_timer:
            silence_timer.cancel()
            silence_timer = None

    def recording_stopped():
        global is_currently_speaking, silence_timer
        is_currently_speaking = False

        # Bắt đầu đếm silence sau 2 giây
        if silence_timer:
            silence_timer.cancel()
        silence_timer = threading.Timer(2.0, add_silence_token)
        silence_timer.start()

    def wakeword_detect_started():
        add_message_to_queue("wakeword_start", "")

    def transcription_started(audio_data):
        add_message_to_queue("transcript_start", "")

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

    recorder_config = {
        'spinner': False,
        'use_microphone': True,  # Thay đổi thành True để dùng microphone
        'model': 'small.en',
        'language': 'en',
        'silero_sensitivity': 0.05,  # Tăng từ 0.01 để ít nhạy hơn
        'webrtc_sensitivity': 2,     # Giảm từ 3 để ít nhạy hơn
        'silero_use_onnx': False,
        'post_speech_silence_duration': 3.0,  # Tăng từ 1.2 lên 3 giây
        'min_length_of_recording': 0.5,       # Tăng từ 0.2 lên 0.5 giây
        'min_gap_between_recordings': 1.0,    # Thêm khoảng cách 1 giây giữa các lần ghi
        'enable_realtime_transcription': True,
        'realtime_processing_pause': 0,
        'realtime_model_type': 'tiny.en',
        'on_realtime_transcription_stabilized': text_detected,
        'on_recording_start': recording_started,
        'on_recording_stop': recording_stopped,  # Thêm callback khi ngưng recording
        'on_vad_detect_start': vad_detect_started,
        'on_wakeword_detection_start': wakeword_detect_started,
        'on_transcription_start': transcription_started,
    }

    recorder = AudioToTextRecorder(**recorder_config)

    def transcriber_thread():
        while True:
            start_transcription_event.wait()
            # Không in gì cả, để cho realtime text handling
            sentence = recorder.transcribe()
            # Cũng không in sentence màu vàng
            add_message_to_queue("full", sentence)
            start_transcription_event.clear()
            if WAIT_FOR_START_COMMAND:
                pass  # Không in waiting message


    def recorder_thread():
        global first_chunk
        while True:
            # Không cần chờ client nữa, chạy trực tiếp
            first_chunk = True
            if WAIT_FOR_START_COMMAND:
                start_recording_event.wait()
            # Không in "waiting for sentence"
            recorder.wait_audio()
            start_transcription_event.set()
            start_recording_event.clear()

    threading.Thread(target=recorder_thread, daemon=True).start()
    threading.Thread(target=transcriber_thread, daemon=True).start()

    print ("\r└─ OK")
    print ("🎤 Microphone ready! Start speaking...")
    print ("Press Ctrl+C to stop")
    print ("└─ ... ", end='', flush=True)

    try:
        # Chạy WebSocket server trong background
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