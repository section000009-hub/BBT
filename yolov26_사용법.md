# 
yolo train model=yolo26s.pt cfg=my_config.yaml

# 기본 학습 명령어 예시:
설명:
model: 사용할 모델 파일 (예: yolo26n.pt는 사전 학습된 모델, yolo26n.yaml은 새 모델 구축).
data: 데이터셋 설정 파일 (예: coco8.yaml은 COCO 데이터셋의 작은 버전).
epochs: 학습 에포크 수 (예: 100).
imgsz: 입력 이미지 크기 (예: 640x640).
추가 옵션 예시:


# 경로 표현 방식:

d:\VIBE\ultralytics-main-yolov26\ultralytics-main\
├── my_config.yaml
└── dataset\
    └── data.yaml
    
./dataset/data.yaml - 현재 디렉토리 기준 (명확함)
dataset/data.yaml - 현재 디렉토리 기준 (간단함)
../dataset/data.yaml - 상위 디렉토리 기준 (필요시)
D:\VIBE\ultralytics-main-yolov26\ultralytics-main\dataset\data.yaml - 절대 경로 (권장하지 않음)
권장사항: 상대 경로(./dataset/data.yaml)를 사용하면 폴더를 이동하거나 다른 환경에서도 유연하게 작동합니다.

실행 명령어 260803

python auto_click_debug.py

또는 파일 경로를 명시하려면:
python D:\VIBE\BBT\auto_click_debug.py

프로그램 기능

- GUI 기반: Tkinter로 만든 윈도우 애플리케이션
- Phase 1 탭: YOLO 모델로 X_BLACK 객체 감지 & 자동 클릭
- Phase 2 탭: O_RED / X_RED (미구성)
- 시뮬레이션: 이미지 폴더에서 가상 클릭 시뮬레이션 가능
- 단축키: F9 키로 캡처 & 추론 & 클릭 실행

260824 기록
버그 2 (시뮬레이션 detection 0개, train 이미지+train 가중치인데도): 이게 진짜 원인입니다 — self.model(img_rgb, ...)처럼 RGB로 변환한 이미지를 YOLO에 넘기고 있는데, Ultralytics는 numpy 배열 입력을 **BGR(cv2.imread 기본 포맷)**로 간주하고 내부적으로 자체적으로 BGR→RGB 변환을 한 번 더 수행합니다. 즉 지금 코드는 채널을 두 번 뒤집는 꼴이라 모델에는 사실상 채널이 반전된 이미지가 들어가고 있었습니다. 학습 때 쓴 원본 이미지+가중치인데도 감지가 안 되는 게 정확히 이 증상과 일치합니다.

260824 기록
Resume this session with:
claude --resume b4d47815-b58e-4000-9d3c-f6da2346317d