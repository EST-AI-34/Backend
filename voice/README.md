# FEST-ON 음성 모델 런타임

AI 안내 화면의 기존 여성 이미지(`/images/perso-ai-guide.png`)는 그대로 사용하고, 이
서비스는 안내 문장을 음성으로 합성합니다. 사진만으로 사람의 목소리를 만들 수는 없으므로
기본 CosyVoice 여성 화자 또는 별도로 준비한 참조 음성을 사용합니다.

## 로컬 실행

CosyVoice 저장소와 모델 가중치는 용량이 크고 GPU/torch 의존성이 있으므로 Git 저장소에
넣지 않습니다. [CosyVoice 공식 저장소](https://github.com/FunAudioLLM/CosyVoice)의 설치
절차에 따라 준비한 뒤 다음 환경 변수를 지정합니다.

```powershell
$env:COSYVOICE_REPO_PATH = "C:\models\CosyVoice"
$env:COSYVOICE_MODEL_PATH = "C:\models\Fun-CosyVoice3-0.5B"
$env:COSYVOICE_PROMPT_WAV = "C:\models\CosyVoice\asset\zero_shot_prompt.wav"

python -m pip install -r backend/voice/requirements.txt
python -m uvicorn backend.voice.server:app --host 127.0.0.1 --port 8100
```

기존 축제 API를 실행하는 셸에는 다음을 지정합니다.

```powershell
$env:VOICE_RUNTIME_URL = "http://127.0.0.1:8100"
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

프론트는 Next 서버의 `/api/voice/synthesize` 프록시를 통해 런타임을 호출합니다. 모델 서버가 아직 설치되지 않았거나
실패하면 `useSpeechOutput`이 자동으로 브라우저 내장 음성으로 대체하므로 화면과 대화 기능은
멈추지 않습니다.

## 확장 파이프라인

- 실시간 AI 안내: CosyVoice 3
- 사전 제작 안내영상: OpenVoice V2 또는 MeloTTS
- 영상 번역·더빙: Whisper/FunASR → 번역기 → CosyVoice → FFmpeg

OpenVoice/MeloTTS와 영상 더빙은 별도 작업 큐로 분리할 수 있도록 `provider` 계약을 유지했습니다.
현재 로컬 런타임에서 실제로 연결된 모델은 한국어 토큰을 명시하는 CosyVoice 3 cross-lingual zero-shot이며, OpenVoice/MeloTTS는 해당 모델의
공식 의존성과 가중치를 준비한 뒤 별도 워커로 붙이는 구조입니다.
