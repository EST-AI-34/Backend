class SurveyRepository:
    def __init__(self) -> None:
        self._questions = [
            {
                "id": "q1",
                "question": "오늘 축제에 전반적으로 얼마나 만족하셨나요?",
                "type": "rating",
                "options": None,
            },
            {
                "id": "q2",
                "question": "가장 만족한 프로그램은 무엇인가요?",
                "type": "choice",
                "options": ["공연", "체험", "먹거리", "전시"],
            },
            {
                "id": "q3",
                "question": "친환경 캠페인에 참여하셨나요?",
                "type": "choice",
                "options": ["참여했어요", "참여하지 않았어요", "다음에 참여할게요"],
            },
            {
                "id": "q4",
                "question": "AI 안내 서비스가 도움이 되었나요?",
                "type": "rating",
                "options": None,
            },
        ]
        self._submissions: list[dict] = []

    def list_questions(self) -> list[dict]:
        return list(self._questions)

    def save_submission(self, payload: dict) -> dict:
        self._submissions.append(payload)
        return {"status": "received", "answer_count": len(payload["answers"])}
