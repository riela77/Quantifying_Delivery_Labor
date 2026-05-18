# Safe-Hour
물동량에만 초점을 맞춘 시스템에서 벗어나, 기사님들의 안전한 근무 시간(Safe Hour)을 시스템적으로 확보해보자. 


## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud 배포 (무료, URL 공유)
1. GitHub 레포 생성 후 이 폴더 통째로 push
2. https://share.streamlit.io 접속 → Deploy an app
3. 레포/브랜치/app.py 선택 → Deploy
4. 생성된 URL 발표 때 클릭 한 번으로 시연

## GeoJSON 업로드
- EPSG:5181 (TM 좌표계) 자동 변환
- 필요 속성: slope_deg, min_width, start_x, start_y, end_x, end_y, seg_id
- 업로드 전까지 난곡동 샘플 배송지로 기본 동작

## 에이전트 구조
- DriverAgent: 법정근무시간 + 피로도 함수 + 도보전환
- CompanyAgent: 물동량 균등 배분
- EnvironmentAgent: GeoJSON 도로 기울기/폭 적용