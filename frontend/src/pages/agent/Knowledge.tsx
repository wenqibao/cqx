import { useState } from "react";
import { Alert, Button, Card, Input, List } from "antd";
import { api } from "../../api/workbench";
import { useResource } from "../../hooks/useResource";
import { DataView, Heading, TechnicalLog } from "../../components/common";
export default function Knowledge() {
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const docs = useResource("knowledge", (s) => api.knowledge(s));
  const search = useResource("search:" + searched, (s) =>
    searched ? api.search(searched, s) : Promise.resolve(null),
  );
  return (
    <>
      <Heading
        title="知识依据"
        description="查阅知识包、引用片段与资料出处。"
        extra={
          <TechnicalLog
            value={{ documents: docs.data, search: search.data }}
            label="知识检索日志"
          />
        }
      />
      <p className="action-note">
        资料为已收录内容的摘编，来源与版本随条目列出。
      </p>
      <Card title="检索知识片段">
        <Input.Search
          aria-label="知识检索关键词"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入关键词，如连续记录血糖"
          enterButton="检索知识"
          onSearch={(v) => v.trim() && setSearched(v.trim())}
        />
        {searched && (
          <DataView resource={search}>
            {(r) =>
              r?.found ? (
                <List
                  dataSource={r.hits}
                  renderItem={(h) => (
                    <List.Item>
                      <div>
                        <h3>{h.title}</h3>
                        <p className="muted">
                          {h.publisher} · 版本 {h.version}
                        </p>

                        <blockquote className="evidence-quote">
                          {h.quote}
                        </blockquote>
                        {h.source_url.startsWith("https://") && (
                          <a
                            href={h.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            查看来源
                          </a>
                        )}
                      </div>
                    </List.Item>
                  )}
                />
              ) : (
                <Alert
                  type="info"
                  title="未找到匹配知识依据"
                  description={r?.note || "资料不足时不生成替代结论。"}
                />
              )
            }
          </DataView>
        )}
      </Card>
      <Card
        title="系统知识包清单"
        extra={<Button onClick={docs.reload}>刷新清单</Button>}
      >
        <DataView resource={docs}>
          {(items) => (
            <List
              dataSource={items}
              renderItem={(d) => (
                <List.Item>
                  <List.Item.Meta
                    title={<>{d.title}</>}
                    description={
                      <>
                        {d.publisher} · 版本 {d.version} · 发布 {d.published_at}
                        <p>
                          {d.source_url.startsWith("https://") && (
                            <a
                              href={d.source_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              原始来源
                            </a>
                          )}
                        </p>
                      </>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </DataView>
      </Card>
    </>
  );
}
