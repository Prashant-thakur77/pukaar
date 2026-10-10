import { useEffect, useRef, useState } from 'react';
import {
  AmbientLight,
  BufferAttribute,
  Color,
  DirectionalLight,
  FogExp2,
  HemisphereLight,
  Mesh,
  MeshStandardMaterial,
  PerspectiveCamera,
  PlaneGeometry,
  Points,
  PointsMaterial,
  BufferGeometry,
  Scene,
  WebGLRenderer,
} from 'three';

/** Heightmap baked by scripts/build_hero_dem.py from Terrain Tiles on AWS. */
interface DemMeta {
  size: number;
  min_m: number;
  max_m: number;
  bbox: [number, number, number, number];
  width_km: number;
}

/** Villages inside the baked area get a light; positions from data/villages.json. */
const LIGHTS: [number, number][] = [
  [31.55929, 77.16515], // Thunag
  [31.57975, 77.04841], // Gohar
  [31.66902, 77.05359], // Pandoh
];

const WORLD = 100; // scene units across the 50 km tile
const NIGHT = new Color('#0b1026');
const LOW = new Color('#16204a');
const MID = new Color('#3a4892');
const HIGH = new Color('#97a4e4');
const SNOW = new Color('#e3e9ff');
const CALM = new Color('#3b82f6');
const ALARM = new Color('#f5a524');

function colourFor(t: number, out: Color): Color {
  if (t < 0.35) return out.copy(LOW).lerp(MID, t / 0.35);
  if (t < 0.8) return out.copy(MID).lerp(HIGH, (t - 0.35) / 0.45);
  return out.copy(HIGH).lerp(SNOW, (t - 0.8) / 0.2);
}

/**
 * The landing hero in 3D: the real Beas valley around Mandi at night. Scrolling
 * raises an illustrative water plane that warms from blue to marigold. The
 * canvas is decorative (aria-hidden); the hero text carries the meaning.
 */
export default function HeroScene({ onReady }: { onReady: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const host = box.current;
    if (!host) return;
    let disposed = false;
    let raf = 0;
    let visible = true;
    const cleanup: (() => void)[] = [];

    (async () => {
      const [meta, buf] = await Promise.all([
        fetch('/hero/mandi-dem.json').then((r) => r.json() as Promise<DemMeta>),
        fetch('/hero/mandi-dem.bin').then((r) => r.arrayBuffer()),
      ]);
      if (disposed) return;
      const n = meta.size;
      const heights = new Uint16Array(buf);
      const span = meta.max_m - meta.min_m;
      const metresPerUnit = (meta.width_km * 1000) / WORLD;
      const exaggeration = 1.6;
      const yOf = (m: number) => ((m - meta.min_m) / metresPerUnit) * exaggeration;

      const renderer = new WebGLRenderer({ antialias: true, powerPreference: 'low-power' });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
      renderer.setSize(host.clientWidth, host.clientHeight);
      renderer.setClearColor(NIGHT);
      host.appendChild(renderer.domElement);
      cleanup.push(() => {
        renderer.dispose();
        renderer.domElement.remove();
      });

      const scene = new Scene();
      scene.fog = new FogExp2(NIGHT, 0.0105);

      const geo = new PlaneGeometry(WORLD, WORLD, n - 1, n - 1);
      geo.rotateX(-Math.PI / 2);
      const pos = geo.attributes.position as BufferAttribute;
      const colours = new Float32Array(pos.count * 3);
      const c = new Color();
      for (let i = 0; i < pos.count; i++) {
        const m = heights[i];
        pos.setY(i, yOf(m));
        colourFor((m - meta.min_m) / span, c).toArray(colours, i * 3);
      }
      geo.setAttribute('color', new BufferAttribute(colours, 3));
      geo.computeVertexNormals();
      const land = new Mesh(geo, new MeshStandardMaterial({ vertexColors: true, roughness: 0.95, metalness: 0 }));
      scene.add(land);

      const waterMat = new MeshStandardMaterial({
        color: CALM,
        emissive: CALM,
        emissiveIntensity: 0.6,
        roughness: 0.25,
        metalness: 0.1,
        transparent: true,
        opacity: 0.82,
      });
      const water = new Mesh(new PlaneGeometry(WORLD, WORLD), waterMat);
      water.rotateX(-Math.PI / 2);
      scene.add(water);

      // Village lights, placed on the terrain.
      const [west, south, east, north] = meta.bbox;
      const lightPos: number[] = [];
      for (const [lat, lon] of LIGHTS) {
        const u = (lon - west) / (east - west);
        const v = (north - lat) / (north - south);
        if (u < 0 || u > 1 || v < 0 || v > 1) continue;
        const gx = Math.round(u * (n - 1));
        const gy = Math.round(v * (n - 1));
        lightPos.push(u * WORLD - WORLD / 2, yOf(heights[gy * n + gx]) + 0.6, v * WORLD - WORLD / 2);
      }
      const lightGeo = new BufferGeometry();
      lightGeo.setAttribute('position', new BufferAttribute(new Float32Array(lightPos), 3));
      const lights = new Points(lightGeo, new PointsMaterial({ color: '#ffc35c', size: 1.4, sizeAttenuation: true, fog: false }));
      scene.add(lights);

      scene.add(new HemisphereLight('#4a5cab', '#070b1d', 1.3));
      scene.add(new AmbientLight('#1b2350', 0.5));
      // Moon behind the ridges for a rim light, plus a soft front fill.
      const moon = new DirectionalLight('#d6deff', 3.4);
      moon.position.set(-25, 35, -70);
      scene.add(moon);
      const fill = new DirectionalLight('#8796d8', 0.8);
      fill.position.set(30, 25, 60);
      scene.add(fill);

      // A fixed star dome, like the SVG valley it replaces.
      let seed = 7;
      const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
      const starPos: number[] = [];
      for (let i = 0; i < 500; i++) {
        const th = rnd() * Math.PI * 2;
        const ph = rnd() * 0.45 + 0.08;
        starPos.push(Math.cos(th) * Math.cos(ph) * 300, Math.sin(ph) * 300, Math.sin(th) * Math.cos(ph) * 300);
      }
      const starGeo = new BufferGeometry();
      starGeo.setAttribute('position', new BufferAttribute(new Float32Array(starPos), 3));
      scene.add(new Points(starGeo, new PointsMaterial({ color: '#dfe5ff', size: 1.1, sizeAttenuation: false, fog: false, transparent: true, opacity: 0.75 })));
      cleanup.push(() => starGeo.dispose());

      const camera = new PerspectiveCamera(38, host.clientWidth / host.clientHeight, 0.5, 400);

      // Water: river level at rest, rising with scroll through the hero.
      const riverY = yOf(meta.min_m + 120);
      const floodY = yOf(meta.min_m + 520);
      let scroll = 0;
      let px = 0;
      let py = 0;
      const onScroll = () => {
        scroll = Math.min(1, Math.max(0, window.scrollY / Math.max(1, host.clientHeight * 0.9)));
      };
      const onPointer = (e: PointerEvent) => {
        px = e.clientX / window.innerWidth - 0.5;
        py = e.clientY / window.innerHeight - 0.5;
      };
      const onResize = () => {
        renderer.setSize(host.clientWidth, host.clientHeight);
        camera.aspect = host.clientWidth / host.clientHeight;
        camera.updateProjectionMatrix();
      };
      window.addEventListener('scroll', onScroll, { passive: true });
      window.addEventListener('pointermove', onPointer, { passive: true });
      window.addEventListener('resize', onResize);
      cleanup.push(() => {
        window.removeEventListener('scroll', onScroll);
        window.removeEventListener('pointermove', onPointer);
        window.removeEventListener('resize', onResize);
      });

      const io = new IntersectionObserver((e) => {
        visible = e.some((x) => x.isIntersecting);
        if (visible && !raf) raf = requestAnimationFrame(frame);
      });
      io.observe(host);
      const onVis = () => {
        if (!document.hidden && visible && !raf) raf = requestAnimationFrame(frame);
      };
      document.addEventListener('visibilitychange', onVis);
      cleanup.push(() => {
        io.disconnect();
        document.removeEventListener('visibilitychange', onVis);
      });

      let level = scroll;
      let first = true;
      const start = performance.now();
      function frame(now: number) {
        raf = 0;
        if (disposed || !visible || document.hidden) return;
        const t = (now - start) / 1000;
        level += (scroll - level) * 0.08;
        water.position.y = riverY + (floodY - riverY) * level;
        const warm = Math.min(1, level * 1.4);
        waterMat.color.copy(CALM).lerp(ALARM, warm);
        waterMat.emissive.copy(CALM).lerp(ALARM, warm);
        waterMat.emissiveIntensity = 0.6 + warm * 0.25;
        waterMat.opacity = 0.82 + warm * 0.12;

        const a = -0.55 + Math.sin(t * 0.05) * 0.12 + px * 0.15;
        const radius = 66 - level * 10;
        camera.position.set(Math.sin(a) * radius, 19 - py * 3 - level * 3, Math.cos(a) * radius);
        camera.lookAt(0, 7 - level * 3, -6);
        renderer.render(scene, camera);
        if (first) {
          first = false;
          setReady(true);
          onReady();
        }
        raf = requestAnimationFrame(frame);
      }
      onScroll();
      raf = requestAnimationFrame(frame);
      cleanup.push(() => {
        geo.dispose();
        lightGeo.dispose();
        (land.material as MeshStandardMaterial).dispose();
        waterMat.dispose();
        water.geometry.dispose();
      });
    })().catch(() => {
      /* keep the SVG valley if the scene cannot start */
    });

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      cleanup.forEach((f) => f());
    };
  }, [onReady]);

  return <div ref={box} className={`hero-3d${ready ? ' is-ready' : ''}`} aria-hidden="true" />;
}
