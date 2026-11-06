import { useState } from "react";
import { Button, Card, List, Tag } from "antd";
import { Link } from "react-router-dom";
import { api } from "../../api/workbench";
import { useWorkbench } from "../../app/WorkbenchContext";
import { useResource } from "../../hooks/useResource";
import {
  DataView,
  ErrorBox,
  Heading,
  Status,
  TechnicalLog,
} from "../../components/common";
import { businessText } from "../../utils/business";
import { noticeLink, when } from "../../utils/format";
export default function Notifications() {
  const { patientId, patient, busy, perform } = useWorkbench();
  const resource = useResource("notices:" + patientId, (s) =>
    api.notifications(patientId, s),
  );
  const [error, setError] = useState<unknown>();
  return (
    <>
      <Heading
        title="通知中心"
        description={`${patient?.name} · 查看提醒与待办`}
        extra={
          <>
            <Button onClick={resource.reload}>刷新通知</Button>
            <TechnicalLog value={resource.data} label="通知日志" />
          </>
        }
      />
      {error && <ErrorBox error={error} />}
      <Card>
        <DataView resource={resource}>
          {(items) => (
            <>
              <p>
                <Tag color="gold">
                  {items.filter((n) => n.status === "unread").length} 条未读
                </Tag>
              </p>
              <List
                dataSource={items}
                locale={{ emptyText: "当前患者暂无通知" }}
                renderItem={(n) => (
                  <List.Item
                    actions={[
                      <Link key="view" to={noticeLink(n)}>
                        查看相关对象
                      </Link>,
                      <Button
                        key="read"
                        size="small"
                        disabled={busy || n.status === "read"}
                        onClick={async () => {
                          setError(undefined);
                          try {
                            await perform(() => api.readNotification(n.id));
                            resource.reload();
                          } catch (e) {
                            setError(e);
                          }
                        }}
                      >
                        {n.status === "read" ? "已读" : "标记已读"}
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <>
                          <Status value={n.status} /> {businessText(n.title)}
                        </>
                      }
                      description={
                        <>
                          <p>{businessText(n.body)}</p>
                          <small>{when(n.created_at)}</small>
                        </>
                      }
                    />
                  </List.Item>
                )}
              />
            </>
          )}
        </DataView>
      </Card>
    </>
  );
}
