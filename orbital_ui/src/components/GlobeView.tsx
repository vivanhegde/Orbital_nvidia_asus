import * as React from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";
import * as THREE from "three";

import {
  LIVE_POINT_RESOLUTION,
  POINTS_TRANSITION_MS,
  livePointColor,
  livePointLabelHtml,
  livePointRadius,
} from "@/components/SatelliteDots";
import type { SatellitePosition } from "@/lib/types";

const INITIAL_LAT = 30;
const INITIAL_LNG = -40;
const INITIAL_ALT = 2.5;
const EARTH_R_KM = 6371;
const EARTH_EQUATORIAL_KM = 6378.137;

const GLOBE_IMG =
  "https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg";
const BUMP_IMG =
  "https://unpkg.com/three-globe/example/img/earth-topology.png";
const BG_IMG =
  "https://unpkg.com/three-globe/example/img/night-sky.png";

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(
      c.getContext("webgl") ??
      (c.getContext("experimental-webgl") as WebGLRenderingContext | null)
    );
  } catch {
    return false;
  }
}

export interface SectorBand {
  altitude_min_km: number;
  altitude_max_km: number;
}

export interface GlobeViewProps {
  points: SatellitePosition[];
  conjunctionStatusMap: ReadonlyMap<number, string>;
  intenseNorads: ReadonlySet<number>;
  sectorBand: SectorBand | null;
  showOrbits: boolean;
  showLabels: boolean;
  autoRotate: boolean;
  selectedPoint?: SatellitePosition | null;
  onPointClick: (p: SatellitePosition) => void;
  onClosePoint?: () => void;
  onViewEvent?: (p: SatellitePosition) => void;
}

export interface GlobeViewHandle {
  flyTo: (
    lat: number,
    lng: number,
    altitude?: number,
    transitionMs?: number,
  ) => void;
  resetCamera: (transitionMs?: number) => void;
  flyToMidpoint: (norad1: number, norad2: number) => void;
}

export const GlobeView = React.forwardRef<GlobeViewHandle, GlobeViewProps>(
  function GlobeView(
    {
      points,
      conjunctionStatusMap,
      intenseNorads,
      sectorBand,
      showOrbits,
      showLabels,
      autoRotate,
      selectedPoint,
      onPointClick,
      onClosePoint,
      onViewEvent,
    },
    ref,
  ): React.ReactElement {
    const globeRef = React.useRef<GlobeMethods | undefined>(undefined);
    const containerRef = React.useRef<HTMLDivElement>(null);
    const [dims, setDims] = React.useState({ w: 800, h: 600 });
    const [webglOk, setWebglOk] = React.useState(true);
    const [hiPulse, setHiPulse] = React.useState(false);
    const [globeReady, setGlobeReady] = React.useState(false);

    React.useImperativeHandle(ref, () => ({
      flyTo(lat, lng, altitude = 2.5, transitionMs = 1_500) {
        globeRef.current?.pointOfView(
          { lat, lng, altitude },
          transitionMs,
        );
      },
      resetCamera(transitionMs = 900) {
        globeRef.current?.pointOfView(
          { lat: INITIAL_LAT, lng: INITIAL_LNG, altitude: INITIAL_ALT },
          transitionMs,
        );
      },
      flyToMidpoint(norad1: number, norad2: number) {
        const p1 = points.find(p => p.norad_id === norad1);
        const p2 = points.find(p => p.norad_id === norad2);
        if (p1 && p2) {
          let lngDiff = p2.lon - p1.lon;
          let lng2 = p2.lon;
          if (lngDiff > 180) lng2 -= 360;
          else if (lngDiff < -180) lng2 += 360;
          const midLng = (p1.lon + lng2) / 2;
          const midLat = (p1.lat + p2.lat) / 2;
          globeRef.current?.pointOfView({ lat: midLat, lng: midLng, altitude: 0.6 }, 1000);
        } else if (p1) {
          globeRef.current?.pointOfView({ lat: p1.lat, lng: p1.lon, altitude: 0.6 }, 1000);
        }
      },
    }));

    React.useEffect(() => {
      setWebglOk(hasWebGL());
    }, []);

    React.useEffect(() => {
      if (!webglOk) {
        setGlobeReady(false);
      }
    }, [webglOk]);

    React.useEffect(() => {
      const el = containerRef.current;
      if (!el) return;
      const resizeObserver = new ResizeObserver((entries) => {
        if (!entries || !entries.length) return;
        if (entries.length === 0) return;
      const { width, height } = entries[0]?.contentRect || { width: 800, height: 600 };
        setDims({ w: width, h: height });
      });
      resizeObserver.observe(el);
      return () => resizeObserver.disconnect();
    }, []);

    React.useEffect(() => {
      if (globeReady && globeRef.current) {
        const controls = globeRef.current.controls() as any;
        if (controls) {
          controls.autoRotate = autoRotate;
          controls.autoRotateSpeed = 0.5;
        }
      }
    }, [autoRotate, globeReady]);

    React.useEffect(() => {
      if (conjunctionStatusMap.size === 0) return;
      const id = window.setInterval(
        () => setHiPulse((p) => !p),
        600,
      );
      return () => window.clearInterval(id);
    }, [conjunctionStatusMap.size]);

    const sectorAltMin = sectorBand?.altitude_min_km ?? null;
    const sectorAltMax = sectorBand?.altitude_max_km ?? null;

    React.useEffect(() => {
      if (!globeReady || sectorAltMin === null || sectorAltMax === null) return;
      const globe = globeRef.current;
      if (!globe) return;

      const maj =
        (EARTH_EQUATORIAL_KM + sectorAltMin) / EARTH_EQUATORIAL_KM;
      const minor =
        (sectorAltMax - sectorAltMin) / EARTH_EQUATORIAL_KM / 2;
      let scene: THREE.Scene;
      try {
        scene = globe.scene();
      } catch {
        return;
      }
      const geom = new THREE.TorusGeometry(maj, minor, 16, 96);
      const mat = new THREE.MeshBasicMaterial({
        color: 0x38bdf8,
        transparent: true,
        opacity: 0.08,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geom, mat);
      const incRad = (53 * Math.PI) / 180;
      mesh.rotation.x = incRad;
      mesh.rotation.y = 0;
      scene.add(mesh);
      return () => {
        try {
          scene.remove(mesh);
        } catch {
          /* scene may be disposed on unmount */
        }
        geom.dispose();
        mat.dispose();
      };
    }, [globeReady, sectorAltMin, sectorAltMax]);

    const lastClickRef = React.useRef<{ t: number; lat: number; lng: number }>({
      t: 0,
      lat: 0,
      lng: 0,
    });

    if (!webglOk) {
      return (
        <div className="flex h-full w-full items-center justify-center bg-slate-950 font-mono text-sm text-slate-400">
          3D globe requires WebGL.
        </div>
      );
    }

    return (
      <div ref={containerRef} className="w-full h-full">
        <Globe
          ref={globeRef}
          width={dims.w}
          height={dims.h}
        backgroundImageUrl={BG_IMG}
        globeImageUrl={GLOBE_IMG}
        bumpImageUrl={BUMP_IMG}
        backgroundColor="rgba(0,0,0,0)"
        atmosphereColor="#3a7bd5"
        atmosphereAltitude={0.18}
        showGlobe
        showAtmosphere
        animateIn
        rendererConfig={{ antialias: true, alpha: true }}
        pointsData={points}
        pointLat="lat"
        pointLng="lon"
        pointAltitude={(d: object) =>
          (d as SatellitePosition).alt_km / EARTH_R_KM
        }
        pointColor={(d: object) => {
          const p = d as SatellitePosition;
          return livePointColor(p, conjunctionStatusMap);
        }}
        pointRadius={(d: object) => {
          const p = d as SatellitePosition;
          return livePointRadius(
            p,
            conjunctionStatusMap,
            intenseNorads,
            hiPulse,
          );
        }}
        pointResolution={LIVE_POINT_RESOLUTION}
        pointsTransitionDuration={POINTS_TRANSITION_MS}
        pointLabel={(d: object) =>
          livePointLabelHtml(d as SatellitePosition)
        }
        pathsData={showOrbits ? points.filter((p) => p.path) : []}
        pathPoints="path"
        pathPointLat={(p: any) => p[0]}
        pathPointLng={(p: any) => p[1]}
        pathPointAlt={(p: any) => p[2] / EARTH_R_KM}
        pathColor={(d: object) => livePointColor(d as SatellitePosition, conjunctionStatusMap)}
        pathResolution={4}
        htmlElementsData={[
          ...(selectedPoint ? [{ ...selectedPoint, _isCard: true }] : []),
          ...(showLabels ? points.map(p => ({ ...p, _isLabel: true })) : [])
        ]}
        htmlLat="lat"
        htmlLng="lon"
        htmlAltitude={(d: object) => ((d as SatellitePosition).alt_km / EARTH_R_KM) + ((d as any)._isLabel ? 0.01 : 0)}
        htmlElement={(d: object) => {
          const p = d as SatellitePosition & { _isCard?: boolean; _isLabel?: boolean };

          if (p._isLabel && !p._isCard) {
            const el = document.createElement("div");
            el.className = "text-[9px] font-mono text-white/70 pointer-events-none whitespace-nowrap drop-shadow-md";
            el.textContent = p.name;
            el.style.transform = "translate(5px, -5px)";
            return el;
          }
          const status = conjunctionStatusMap.get(p.norad_id);
          const isUrgent = status === "action";
          const isWatch = status === "watch";
          const badgeText = isUrgent ? "URGENT" : isWatch ? "WATCH" : "LOW";
          const badgeColor = isUrgent ? "bg-red-500/20 text-red-400" : isWatch ? "bg-amber-500/20 text-amber-400" : "bg-green-500/10 text-green-500";

          const el = document.createElement("div");
          // Apply tailwind classes
          el.className = "bg-[#0d1a2d] border border-[rgba(255,255,255,0.2)] rounded-lg shadow-xl flex flex-col p-3 font-mono text-sm w-64 text-slate-200 pointer-events-auto backdrop-blur-sm z-50";
          el.style.transform = "translate(-50%, -100%)";
          el.style.marginTop = "-15px";

          el.innerHTML = `
            <div class="flex justify-between items-center mb-2 border-b border-[rgba(255,255,255,0.1)] pb-2">
              <span class="font-bold truncate pr-2 text-slate-100">${p.name}</span>
              <button id="close-btn-${p.norad_id}" class="text-slate-500 hover:text-white cursor-pointer px-1 font-bold">&times;</button>
            </div>
            <div class="flex flex-col gap-1.5 text-xs mb-3">
              <div class="flex justify-between text-slate-400"><span>NORAD ID</span> <span class="text-slate-200">${p.norad_id}</span></div>
              <div class="flex justify-between text-slate-400"><span>Type</span> <span class="text-slate-200">${p.type}</span></div>
              <div class="flex justify-between text-slate-400"><span>Altitude</span> <span class="text-slate-200">${p.alt_km.toFixed(0)} km</span></div>
            </div>
            ${status ? `
              <div class="flex justify-between items-center mb-3">
                <span class="text-slate-400 text-xs">Conjunction</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider ${badgeColor}">${badgeText}</span>
              </div>
            ` : `
              <div class="flex justify-between items-center mb-3">
                <span class="text-slate-400 text-xs">Status</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider bg-slate-500/20 text-slate-400">NOMINAL</span>
              </div>
            `}
            ${status ? `
              <button id="view-btn-${p.norad_id}" class="w-full py-1.5 mt-1 bg-[#378add]/20 text-[#378add] hover:bg-[#378add]/40 border border-[#378add]/50 rounded text-xs font-bold transition-colors shadow-sm">
                View Event Details
              </button>
            ` : ""}
          `;

          // Using setTimeout to ensure element is in DOM if needed, but direct listeners usually work.
          // Since it's created but not mounted yet, we attach events directly to the node.
          const closeBtn = el.querySelector(`#close-btn-${p.norad_id}`);
          if (closeBtn && onClosePoint) {
            closeBtn.addEventListener("click", (e) => {
              e.stopPropagation();
              onClosePoint();
            });
            // also support touchend for mobile
            closeBtn.addEventListener("touchend", (e) => {
              e.stopPropagation();
              onClosePoint();
            });
          }

          const viewBtn = el.querySelector(`#view-btn-${p.norad_id}`);
          if (viewBtn && onViewEvent) {
            viewBtn.addEventListener("click", (e) => {
              e.stopPropagation();
              onViewEvent(p);
            });
            viewBtn.addEventListener("touchend", (e) => {
              e.stopPropagation();
              onViewEvent(p);
            });
          }

          return el;
        }}
        onPointClick={(p: object) => onPointClick(p as SatellitePosition)}
        onGlobeClick={(coords, event) => {
          if (event.detail === 2) {
            globeRef.current?.pointOfView(
              { lat: INITIAL_LAT, lng: INITIAL_LNG, altitude: INITIAL_ALT },
              1000,
            );
            return;
          }
          const now = performance.now();
          const prev = lastClickRef.current;
          const dup =
            Math.abs(coords.lat - prev.lat) < 0.05 &&
            Math.abs(coords.lng - prev.lng) < 0.05;
          if (dup && now - prev.t < 320) {
            globeRef.current?.pointOfView(
              { lat: INITIAL_LAT, lng: INITIAL_LNG, altitude: INITIAL_ALT },
              1000,
            );
            lastClickRef.current = { t: 0, lat: 0, lng: 0 };
            return;
          }
          lastClickRef.current = { t: now, lat: coords.lat, lng: coords.lng };
        }}
        onGlobeReady={() => {
          globeRef.current?.pointOfView(
            { lat: INITIAL_LAT, lng: INITIAL_LNG, altitude: INITIAL_ALT },
            0,
          );
          if (globeRef.current) {
            const controls = globeRef.current.controls() as any;
            if (controls) {
              controls.autoRotate = autoRotate;
              controls.autoRotateSpeed = 0.5;
            }
          }
          setGlobeReady(true);
        }}
      />
      </div>
    );
  },
);
