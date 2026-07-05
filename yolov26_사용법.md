# 
yolo train model=yolo26n.pt cfg=my_config.yaml

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