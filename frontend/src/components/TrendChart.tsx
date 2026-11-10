import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { Empty } from "antd";
import type { HealthRecord } from "../api/types";
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
export function TrendChart({ records }: { records: HealthRecord[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const points = records
    .filter((r) => r.kind === "fasting_glucose" && r.value !== null)
    .sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
  useEffect(() => {
    if (!ref.current || !points.length) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
      color: ["#087f8c"],
      tooltip: { trigger: "axis" },
      grid: { left: 52, right: 24, top: 38, bottom: 40 },
      xAxis: { type: "time" },
      yAxis: { type: "value", name: "mmol/L", min: 0 },
      series: [
        {
          name: "空腹血糖",
          type: "line",
          smooth: false,
          connectNulls: false,
          symbolSize: 7,
          data: points.map((r) => [r.recorded_at, r.value]),
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [records]);
  return points.length ? (
    <>
      <div
        ref={ref}
        className="trend"
        role="img"
        aria-label="实际空腹血糖记录趋势"
      />
      <p className="muted">
        仅连接真实观测点；未补齐缺失记录、未设临床目标线。
      </p>
    </>
  ) : (
    <Empty description="此时间窗口内暂无空腹血糖记录" />
  );
}
