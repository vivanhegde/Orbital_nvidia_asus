import * as React from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { CatalogSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROW_ORDER: readonly string[] = [
  "starlink",
  "stations",
  "fengyun-1c-debris",
  "cosmos-2251-debris",
  "iridium-33-debris",
] as const;

export interface CatalogSummaryProps {
  summary: CatalogSummary | undefined;
  loading: boolean;
  className?: string;
}

export function CatalogSummary({
  summary,
  loading,
  className,
}: CatalogSummaryProps): React.ReactElement {
  return (
    <Card
      className={cn(
        "border-cyan-500/20 bg-[rgba(8,15,30,0.65)] shadow-lg shadow-black/40 backdrop-blur-md",
        className,
      )}
    >
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-slate-300">
          Catalog
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading && !summary ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <div className="overflow-hidden rounded border border-mission-border">
            <table className="w-full font-mono text-xs">
              <thead className="bg-slate-900/80 text-left text-slate-500">
                <tr>
                  <th className="p-2">Group</th>
                  <th className="p-2 text-right">Objects</th>
                </tr>
              </thead>
              <tbody>
                {ROW_ORDER.map((g) => (
                  <tr
                    key={g}
                    className="border-t border-mission-border text-slate-300"
                  >
                    <td className="p-2">{g}</td>
                    <td className="p-2 text-right tabular-nums">
                      {summary?.by_group[g] ?? "—"}
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-slate-700 bg-slate-900/50 font-medium text-cyan-300">
                  <td className="p-2">Total</td>
                  <td className="p-2 text-right tabular-nums">
                    {summary?.total_objects ?? "—"}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
