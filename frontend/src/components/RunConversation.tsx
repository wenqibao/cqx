import { Button, Tag } from "antd";
import { Link } from "react-router-dom";
import { api } from "../api/workbench";
import { useResource } from "../hooks/useResource";
import { array, link, obj } from "../utils/format";
import { businessText, relatedQuestions } from "../utils/business";

// 仅展示本次运行的原始消息和问题。待回答入口以真实问题状态为准，读取不触发Agent。
export function RunConversation({
  run,
  patientId,
  questions,
}: {
  run: Record<string, unknown>;
  patientId: string;
  questions?: Record<string, unknown>[];
}) {
  const runId = String(run.id || run.run_id || "");
  const waiting = run.status === "waiting_user";
  const resource = useResource(
    `conversation:${patientId}:${runId}:${run.status}`,
    (signal) =>
      waiting
        ? api.questions(patientId, signal)
        : Promise.resolve(questions || []),
  );
  const actual = resource.data || questions || [];
  const related = relatedQuestions({ ...run, patient_id: patientId }, actual);
  const pending =
    waiting && !resource.loading && !resource.error
      ? related.filter((q) => q.status === "waiting")
      : [];
  const responses = array(obj(run.output).responses ?? run.responses).filter(
    (v): v is string => typeof v === "string" && !!v.trim(),
  );
  const message = obj(run.input).message;
  return (
    <section className="run-conversation" aria-label="本次沟通">
      {pending.map((q) => (
        <div className="conversation-message agent-message" key={String(q.id)}>
          <span className="message-speaker">Agent 提问</span>
          <p>{businessText(q.question)}</p>
          <Link to={link("/followups", patientId, { question: String(q.id) })}>
            <Button type="primary">去回答</Button>
          </Link>
        </div>
      ))}
      {typeof message === "string" && message.trim() && (
        <div className="conversation-message patient-message">
          <span className="message-speaker">患者消息</span>
          <p>{businessText(message)}</p>
        </div>
      )}
      {related
        .filter((q) => !pending.includes(q))
        .map((q) => (
          <div key={String(q.id)}>
            <div className="conversation-message agent-message">
              <span className="message-speaker">Agent 提问</span>
              <p>{businessText(q.question)}</p>
            </div>
            {typeof q.answer_text === "string" && q.answer_text && (
              <div className="conversation-message patient-message">
                <span className="message-speaker">患者答复 · 模拟</span>
                <p>{businessText(q.answer_text)}</p>
                {obj(q.answer).uncertain === true && (
                  <Tag color="gold">尚不确定</Tag>
                )}
              </div>
            )}
          </div>
        ))}
      {responses.map((response, i) => (
        <div key={i} className="conversation-message agent-message">
          <span className="message-speaker">Agent 回复</span>
          <p>{businessText(response)}</p>
        </div>
      ))}
      {!responses.length && !related.length && !waiting && (
        <p className="muted">本次未返回对话内容，处理结果见下方。</p>
      )}
      {waiting && resource.loading && (
        <p role="status">正在查找待回答的问题…</p>
      )}
      {waiting && !!resource.error && (
        <div role="alert">
          <p>暂时无法读取待回答问题。</p>
          <Button onClick={resource.reload}>重新读取问题</Button>
        </div>
      )}
      {waiting && !resource.loading && !resource.error && !pending.length && (
        <p>
          当前没有查到本次运行的待回答问题。
          <Link to={link("/followups", patientId)}>查看随访列表</Link>
        </p>
      )}
    </section>
  );
}
