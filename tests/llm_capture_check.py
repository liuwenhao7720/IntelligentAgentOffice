import sys
sys.path.insert(0, "/app")
from app.services.task_agent import capture_with_llm

texts = [
    "明天上午9点半开项目例会，下午把周报初稿发给王经理，周五前必须回复客户关于材质的澄清函",
    "领导临时安排：周四前完成屏蔽泵选型计算书；另外帮我盯一下采购的合同盖章进度",
]
for t in texts:
    r = capture_with_llm(t, source="wecom", owner="回归测试")
    print("mode =", r["mode"], "| count =", r["count"])
    for c in r["candidates"]:
        print("  -", c.get("title"), "| 会议:", c.get("is_meeting"), "| 时间:", c.get("ai_fixed_start"),
              "| 截止:", c.get("due_time"), "| 急", c.get("ai_urgency"), "重", c.get("ai_importance"),
              "| 他人:", c.get("is_other_request"))
    assert r["count"] >= 1, "未抽取到任务"
    assert all(x.get("title") for x in r["candidates"])
print("LLM 采集回归 OK")
