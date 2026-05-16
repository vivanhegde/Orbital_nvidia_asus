import * as React from "react";

const STEPS = [
  "Acknowledged high-risk conjunction event.",
  "Fetching object metadata and historical maneuvers...",
  "Querying historical operator decisions for similar pairs...",
  "Re-propagating orbit trajectories with latest SGP4 TLEs...",
  "Evaluating atmospheric drag models against current Kp index...",
  "Computing refined Probability of Collision (Pc)...",
  "Threshold exceeded. Escalating to URGENT review queue."
];

export function AgentReasoningStream() {
  const [activeStepIndex, setActiveStepIndex] = React.useState(0);
  const [visibleText, setVisibleText] = React.useState("");
  
  React.useEffect(() => {
    if (activeStepIndex >= STEPS.length) return;
    
    const targetText = STEPS[activeStepIndex];
    if (visibleText === targetText) {
      const timer = setTimeout(() => {
        setActiveStepIndex(s => s + 1);
        setVisibleText("");
      }, 600);
      return () => clearTimeout(timer);
    }
    
    const timer = setTimeout(() => {
      setVisibleText((targetText ?? "").slice(0, visibleText.length + 1));
    }, 25);
    
    return () => clearTimeout(timer);
  }, [activeStepIndex, visibleText]);

  return (
    <div className="flex flex-col gap-2 p-4 bg-[#060b14] rounded-b-lg text-xs font-mono w-full min-h-[180px]">
      {STEPS.map((step, i) => {
        if (i > activeStepIndex) return null;
        const isActive = i === activeStepIndex;
        const text = isActive ? visibleText : step;
        
        return (
          <div key={i} className={`flex gap-3 transition-opacity duration-300 ${isActive && visibleText.length === 0 ? "opacity-0" : "opacity-100"}`}>
            <span className="text-[#3a5060] font-bold shrink-0">{i + 1}.</span>
            <span className={isActive ? "text-amber-400" : "text-[#7a9ab0]"}>
              {text}
              {isActive && (
                <span className="inline-block w-1.5 h-3 bg-amber-400 ml-1 animate-pulse" style={{ verticalAlign: 'baseline', marginBottom: '-2px' }}></span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
