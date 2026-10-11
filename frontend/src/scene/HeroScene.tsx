import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Group } from "three";

function Coins() {
  const group = useRef<Group>(null);

  useFrame((_, dt) => {
    if (group.current) {
      group.current.rotation.y += dt * 0.35;
    }
  });

  return (
    <group ref={group} rotation={[0.45, 0, 0.12]}>
      {[0, 1, 2, 3].map((i) => (
        <mesh key={i} position={[0, i * 0.34 - 0.5, 0]}>
          <cylinderGeometry args={[1.1, 1.1, 0.24, 48]} />
          <meshStandardMaterial
            color={i % 2 ? "#0d7a4a" : "#1c2a23"}
            roughness={0.45}
            metalness={0.25}
          />
        </mesh>
      ))}
    </group>
  );
}

export default function HeroScene() {
  return (
    <Canvas
      dpr={1}
      camera={{ position: [0, 0.6, 4.2], fov: 40 }}
      gl={{
        antialias: false,
        powerPreference: "low-power",
        failIfMajorPerformanceCaveat: true,
      }}
      onCreated={({ gl }) => {
        const context = gl.getContext();

        if (
          !context ||
          context.isContextLost() ||
          context.getShaderPrecisionFormat(
            context.VERTEX_SHADER,
            context.HIGH_FLOAT,
          ) === null
        ) {
          throw new Error("WebGL shader precision is unavailable.");
        }
      }}
      aria-hidden="true"
    >
      <ambientLight intensity={0.9} />
      <directionalLight position={[3, 4, 2]} intensity={1.4} />
      <Coins />
    </Canvas>
  );
}