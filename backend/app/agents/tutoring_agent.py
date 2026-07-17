from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentMessage, TutoringOutput
from app.agents.state import AgentGraphState


class TutoringAgent(BaseAgent):
    name = "tutoring_agent"
    system_prompt_path = "app/agents/prompts/tutoring_agent.md"

    async def run(self, message: AgentMessage) -> dict[str, Any]:
        return self.execute(message.payload)

    def execute(self, state: AgentGraphState | dict[str, Any]) -> dict[str, Any]:
        text = str(state.get("feedback_text") or state.get("comment") or "").strip()
        quick = str(state.get("feedback_intent") or state.get("feedback_type") or "other")
        turn_count = int(state.get("tutoring_turn_count") or 1)
        if quick in {"incorrect", "has_error"} or any(
            term in text for term in ("错误", "不对", "有误")
        ):
            intent, action = "incorrect", "review"
            reply = "已记录疑似错误位置。我会重新检索来源并复核资源，但不会据此降低你的能力画像。"
        elif quick == "too_easy" or any(
            term in text for term in ("太简单", "已经会", "更难")
        ):
            intent, action = "too_easy", "challenge"
            reply = "我会用迁移问题确认掌握程度，再生成与当前知识点关联的挑战任务。"
        elif quick == "too_hard" or any(
            term in text for term in ("太难", "不会", "看不懂")
        ):
            intent, action = "too_hard", "explain"
            reply = "先确认困难位置：是概念、代码步骤，还是结果验证让你卡住？"
        elif quick == "helpful" or any(
            term in text for term in ("有帮助", "明白了", "掌握")
        ):
            intent, action = "helpful", "no_change"
            reply = "已记录本轮学习效果，后续计分结果可作为画像更新证据。"
        else:
            intent, action = "confusing", "explain"
            reply = "请指出最困惑的概念或步骤。我会先给提示，再根据后续回答调整解释。"

        if action == "explain" and turn_count < 2:
            action = "no_change"
        evidence = [{"type": "tutoring_message", "summary": text[:120]}] if text else []
        return TutoringOutput(
            feedback_intent=intent,
            recommended_action=action,
            reply=reply,
            profile_update_required=False,
            evidence=evidence,
            decision_reason="单次主观反馈仅作为辅助证据，不直接修改能力画像。",
        ).model_dump()
