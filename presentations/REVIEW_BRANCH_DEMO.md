# 录制三种复评分支

第 14 页先展示林泽远的「正常关闭」，再打开周承安的复评页。周承安的步数记录不足，显示「缺少数据」并关联「补充近期活动步数」。同页可展示已有的低血糖「待人工复核」。两条复评分别处理活动记录和低血糖事项。

## 生成缺少数据的案例

从仓库根目录运行。先准备已导入视频数据包的合成演示库副本，确认其中有 `VDEMO-104`。使用数据包原名时，该患者显示为「视频演示病例04（虚构）」。[视频数据包 PR](https://github.com/wenqibao/cqx/pull/16)

```powershell
python -m presentations.add_missing_data_demo --db "D:/path/to/diabetes_agent_video_demo.db"
```

脚本用已有任务和复评服务创建补录任务，再人工发起规则复评。输出应包含 `branch=MISSING_DATA`、`status=completed` 和 `missing_required_fields=["steps"]`。同一数据库中重复运行会返回已有复评。原有复核和健康记录继续保留，脚本执行期间厂商请求为 0。

让演示后端连接上述数据库，进入「任务与复评」的「动态复评与人工复核」，选中周承安。使用 5182 录制环境时可直达。[周承安的复评页](http://127.0.0.1:5182/tasks?patient=VDEMO-104&tab=reviews)

口播可用「这条活动记录复评发现缺少步数，关联任务要求补录。另一条低血糖事项继续由医护人员复核。」自动到期调度可以另录项目的调度场景。[调度演示脚本说明](../docs/demo_script.md)
