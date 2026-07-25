import { useRef, useState, useEffect } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { useGLTF, OrbitControls, ContactShadows } from '@react-three/drei'
import * as THREE from 'three'

// 3D 模型路径映射
const MODEL_PATHS: Record<string, string> = {
  bull: '/models/michelle.glb',
  bear: '/models/michelle.glb',
  macro: '/models/cesium-man.glb',
  risk: '/models/xbot.glb',
  audit: '/models/xbot.glb',
  chair: '/models/cesium-man.glb',
}

// 角色颜色
const ROLE_COLORS: Record<string, string> = {
  bull: '#2dd4bf',
  bear: '#fb7185',
  macro: '#a78bfa',
  risk: '#fbbf24',
  audit: '#ff3b5c',
  chair: '#3fd3e6',
}

interface ModelProps {
  role: string
  speaking: boolean
}

function Model({ role, speaking }: ModelProps) {
  const path = MODEL_PATHS[role] || '/models/michelle.glb'
  const { scene } = useGLTF(path)
  const ref = useRef<THREE.Group>(null)
  const [hovered, setHovered] = useState(false)

  // 克隆场景以避免多个实例冲突
  const [clonedScene, setClonedScene] = useState<any>(null)
  useEffect(() => {
    if (scene) {
      const clone = scene.clone()
      setClonedScene(clone)
    }
  }, [scene])

  // 动画
  useFrame((state) => {
    if (!ref.current) return

    if (speaking) {
      // 说话时上下浮动
      ref.current.position.y = Math.sin(state.clock.elapsedTime * 3) * 0.1
      // 轻微旋转
      ref.current.rotation.y = Math.sin(state.clock.elapsedTime * 2) * 0.1
    } else {
      // 待机动画
      ref.current.position.y = Math.sin(state.clock.elapsedTime * 1.5) * 0.05
      ref.current.rotation.y = 0
    }

    // 鼠标悬停效果
    if (hovered) {
      ref.current.scale.setScalar(1.05)
    } else {
      ref.current.scale.setScalar(1)
    }
  })

  const displayScene = clonedScene || scene

  return (
    <group
      ref={ref}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
    >
      <primitive object={displayScene} />
      {/* 角色颜色光晕 */}
      <pointLight
        position={[0, 2, 0]}
        intensity={speaking ? 3 : 1}
        color={ROLE_COLORS[role]}
        distance={5}
      />
    </group>
  )
}

interface Avatar3DProps {
  role: string
  speaking?: boolean
  size?: number
}

export function Avatar3D({ role, speaking = false, size = 200 }: Avatar3DProps) {
  return (
    <div style={{ width: size, height: size }}>
      <Canvas
        camera={{ position: [0, 1, 2.2], fov: 35 }}
        style={{ background: 'transparent' }}
        gl={{ alpha: true, antialias: true }}
      >
        {/* 灯光 - 更亮 */}
        <ambientLight intensity={1.2} />
        <directionalLight position={[5, 5, 5]} intensity={1.5} />
        <directionalLight position={[-5, 3, -5]} intensity={0.8} />
        <pointLight position={[0, 3, 0]} intensity={1} color="#ffffff" />

        {/* 模型 - 调整位置让头部在中心，缩小比例 */}
        <group position={[0, -0.8, 0]} scale={0.8}>
          <Model role={role} speaking={speaking} />
        </group>

        {/* 阴影 */}
        <ContactShadows
          position={[0, -0.8, 0]}
          opacity={0.3}
          scale={4}
          blur={2}
          far={1.5}
        />

        {/* 控制器 */}
        <OrbitControls
          enableZoom={false}
          enablePan={false}
          minPolarAngle={Math.PI / 3}
          maxPolarAngle={Math.PI / 1.8}
        />
      </Canvas>
    </div>
  )
}

// 预加载所有模型
export function preloadModels() {
  Object.values(MODEL_PATHS).forEach((path) => {
    useGLTF.preload(path)
  })
}
