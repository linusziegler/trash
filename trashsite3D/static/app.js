import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as CANNON from 'cannon';

// Three.js Scene Setup
let scene, camera, renderer;
let objects = [];
let selectedObjectIndex = null; // Always track selected by index
let loadedObjectIds = new Set();
let cameraBasePos = new THREE.Vector3(0, 15, 25);
let gltfLoader = new GLTFLoader();

const itemsPerRow = 10;

// Zoom/Inspect mode
let isZoomed = false;
let zoomDistance = 10; // Close-up distance for inspecting
let normalDistance = 35; // Normal grid view distance

// Auto-select first object when it loads
let shouldSelectFirstObject = false;
let firstObjectSelected = false;

// Grid navigation uses row/col instead of array index
let selectedRow = 0;
let selectedCol = 0;

// key-mapping for navigation using custom keyboard
let customKeyMapping = false; // Set to true to enable custom key mapping
const keyMap = {
    "c" : 'ArrowUp',
    "m" : 'ArrowDown',
    "t" : 'ArrowLeft',
    "ArrowDown" : 'ArrowRight' ,
    "ArrowUp" : 'i',
    "i" : 'p',
};

// Physics
let physicsWorld;
let physicsEnabled = false;
let currentViewMode = 'grid'; // 'grid' or 'pile'
let physicsObjects = new Map(); // Maps Three.js object to physics body

// Store initial state
let initialObjectPositions = new Map();
let initialCameraPos = new THREE.Vector3();

function init() {
    console.log('Initializing 3D scene...');

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xdbdbdb);

    // Camera - fixed orthogonal position
    camera = new THREE.PerspectiveCamera(
        45,
        window.innerWidth / window.innerHeight,
        0.1,
        100
    );
    cameraBasePos = new THREE.Vector3(0, 0, 35);
    camera.position.copy(cameraBasePos);
    camera.lookAt(0, 0, 0);
    initialCameraPos.copy(camera.position);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowShadowMap;
    const container = document.getElementById('canvas-container');
    console.log('Canvas container:', container);
    container.appendChild(renderer.domElement);
    console.log('Renderer initialized');

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(10, 20, 10);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.width = 2048;
    directionalLight.shadow.mapSize.height = 2048;
    directionalLight.shadow.camera.left = -50;
    directionalLight.shadow.camera.right = 50;
    directionalLight.shadow.camera.top = 50;
    directionalLight.shadow.camera.bottom = -50;
    scene.add(directionalLight);    
    console.log('Lighting initialized');

    // Initialize physics world
    initPhysics();

    // Event Listeners
    window.addEventListener('resize', onWindowResize);
    document.addEventListener('keydown', onKeyDown);
    console.log('Event listeners added (keyboard control mode)');

    // Start the animation loop
    animate();
    console.log('Animation loop started');

    // Load initial objects
    loadObjects();
    console.log('Objects loading...');

    // Poll for new objects every 2 seconds
    setInterval(loadObjects, 2000);
}

function initPhysics() {
    // Create physics world
    physicsWorld = new CANNON.World();
    physicsWorld.gravity.set(0, -10, 0);
    physicsWorld.defaultContactMaterial.friction = 0.8;
    
    // Create invisible floor
    const floorShape = new CANNON.Plane();
    const floorBody = new CANNON.Body({
        mass: 0,
        shape: floorShape
    });
    floorBody.quaternion.setFromAxisAngle(new CANNON.Vec3(1, 0, 0), -Math.PI / 2);
    floorBody.position.y = -200; // Position floor well below all objects
    physicsWorld.addBody(floorBody);
    
    console.log('Physics world initialized');
}

function findObjectByGridCoordinates(row, col) {
    // Find object at specific grid coordinates
    for (let i = 0; i < objects.length; i++) {
        const obj = objects[i];
        if (obj.userData.row === row && obj.userData.col === col) {
            return i;
        }
    }
    return null;
}

function getNeighbor(direction) {
    let newRow = selectedRow;
    let newCol = selectedCol;
    
    // Calculate max row based on objects loaded
    const maxRow = Math.ceil(objects.length / itemsPerRow) - 1;
    
    switch(direction) {
        case 'ArrowUp':
            newRow = Math.max(0, newRow - 1);
            break;
        case 'ArrowDown':
            newRow = Math.min(maxRow, newRow + 1);
            break;
        case 'ArrowLeft':
            newCol = Math.max(0, newCol - 1);
            break;
        case 'ArrowRight':
            newCol = Math.min(itemsPerRow - 1, newCol + 1);
            break;
    }
    
    // Find object at new coordinates
    const neighborIndex = findObjectByGridCoordinates(newRow, newCol);
    if (neighborIndex !== null) {
        selectedRow = newRow;
        selectedCol = newCol;
        return neighborIndex;
    }
    return null;
}

function createPhysicsBody(object) {
    // Calculate bounding box to get approximate dimensions
    const bbox = new THREE.Box3().setFromObject(object);
    const size = bbox.getSize(new THREE.Vector3());
    
    // Create physics body with approximate sphere
    const radius = Math.max(size.x, size.y, size.z) / 2;
    const shape = new CANNON.Sphere(radius);
    
    const body = new CANNON.Body({
        mass: 2,
        shape: shape,
        friction: 1,
        restitution: 0.05,
        linearDamping: 0.5,
        angularDamping: 0.8
    });
    
    body.position.set(
        object.position.x,
        object.position.y,
        object.position.z
    );
    
    // Reset velocity to ensure clean state
    body.velocity.x = 0;
    body.velocity.y = 0;
    body.velocity.z = 0;
    body.angularVelocity.x = 0;
    body.angularVelocity.y = 0;
    body.angularVelocity.z = 0;
    
    physicsWorld.addBody(body);
    physicsObjects.set(object, body);
}

function switchToPileView() {
    console.log('Switching to pile view...');
    currentViewMode = 'pile';
    physicsEnabled = true;

    initPhysics(); 
    
    // Create physics bodies for all objects
    objects.forEach(obj => {
        createPhysicsBody(obj);
    });
    

}

function switchToGridView() {
    console.log('Switching to grid view...');
    currentViewMode = 'grid';
    physicsEnabled = false;
    
    // Remove all physics bodies
    physicsObjects.forEach((body, obj) => {
        physicsWorld.removeBody(body);
    });
    physicsObjects.clear();
    
    // Reset objects to grid positions
    objects.forEach((obj, index) => {
        const gridPos = gridLayout(index);
        obj.position.copy(gridPos);
        obj.rotation.set(0, 0, 0);
        obj.velocity = new THREE.Vector3(0, 0, 0);
        // Reset position to initial grid position
        if (initialObjectPositions.has(obj)) {
            obj.position.copy(initialObjectPositions.get(obj));
        }
    });
    

}

function toggleViewMode() {
    if (currentViewMode === 'grid') {
        switchToPileView();
    } else {
        switchToGridView();
    }
}

function loadObject(name, position, id, fileSize, addedTime, row, col, status = 'ready') {
    // Try to load GLB file, fallback to cube if not found
    const glbPath = `objects/${id}.glb`;

    gltfLoader.load(
        glbPath,
        function (gltf) {
            // GLB loaded successfully
            const model = gltf.scene;

            // Normalize scale - calculate bounding box and scale to fit in 2x2x2 unit cube
            const bbox = new THREE.Box3().setFromObject(model);
            const size = bbox.getSize(new THREE.Vector3());
            const maxDim = Math.max(size.x, size.y, size.z);
            const scale = 3 / maxDim;

            // Bake scale into geometry
            model.traverse((child) => {
                if (child instanceof THREE.Mesh) {
                    child.geometry.applyMatrix4(new THREE.Matrix4().makeScale(scale, scale, scale));
                }
            });

            // add invisible hitbox for easier raycasting
            const bboxHelper = new THREE.Box3().setFromObject(model);
            const bboxSize = bboxHelper.getSize(new THREE.Vector3());
            const bboxGeometry = new THREE.BoxGeometry(bboxSize.x, bboxSize.y, bboxSize.z);
            const bboxMaterial = new THREE.MeshBasicMaterial({ visible: false });
            const bboxMesh = new THREE.Mesh(bboxGeometry, bboxMaterial);
            bboxMesh.position.copy(bboxHelper.getCenter(new THREE.Vector3()));
            model.add(bboxMesh);

            // Center the model
            const center = bbox.getCenter(new THREE.Vector3());
            model.position.copy(position);
            model.position.sub(center.multiplyScalar(scale));

            model.castShadow = false;
            model.receiveShadow = false;

            // Count vertices in the loaded model
            let vertexCount = 0;
            model.traverse((child) => {
                if (child instanceof THREE.Mesh) {
                    vertexCount += child.geometry.attributes.position.count;
                    child.castShadow = false;
                    child.receiveShadow = false;
                    child.material.color = new THREE.Color(0xffffff);
                    child.material.emissive = new THREE.Color(0x8846fa);
                    child.material.emissiveIntensity = 0.;
                }
            });

            // Store metadata with pre-calculated row/col
            model.userData = {
                id: id,
                name: name,
                added: new Date(addedTime).toLocaleString(),
                gridPosition: position.clone(),
                isSelected: false,
                vertexCount: vertexCount,
                fileSize: (fileSize) / (1024 * 1024), // Convert bytes to MB
                status: 'ready',
                isLoading: false,
                row: row,
                col: col
            };

            scene.add(model);
            objects.push(model);
            console.log('Object added to scene and array. Total objects now:', objects.length, 'Name:', name);
            initialObjectPositions.set(model, position.clone());
            
            // If this is the first object and we're in first-load mode, select it
            if (shouldSelectFirstObject && !firstObjectSelected && objects.length === 1) {
                console.log('First object loaded! Selecting it.');
                setTimeout(() => selectObjectByIndex(0), 100);
                firstObjectSelected = true;
            }
        },
        undefined,
        function (error) {
            // GLB failed to load, create fallback cube
            console.log('GLB not found or failed to load for', id, '- using cube fallback');
            createFallbackCube(name, position, id, row, col, status);
        }
    );
}

function createFallbackCube(name, position, id, row, col, status = 'ready') {
    // Fallback: create a simple cube with different styling based on status
    const isLoading = status === 'loading';
    
    const material = new THREE.MeshStandardMaterial({
        color: isLoading ? new THREE.Color(0x6b7a8f) : new THREE.Color(0xb0b0b0),
        metalness: isLoading ? 0.4 : 0.7,
        roughness: isLoading ? 0.6 : 0.2,
        emissive: isLoading ? new THREE.Color(0x4a5f7f) : new THREE.Color(0x8846fa),
        emissiveIntensity: isLoading ? 0.3 : 0.
    });

    const geometry = new THREE.BoxGeometry(2, 2, 2);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(position);
    mesh.castShadow = false;
    mesh.receiveShadow = false;

    // Store metadata with pre-calculated row/col
    mesh.userData = {
        id: id,
        name: isLoading ? "loading..." : name,
        added: new Date().toLocaleString(),
        gridPosition: position.clone(),
        isSelected: false,
        vertexCount: 0,
        fileSize: 0,
        status: status,
        isLoading: isLoading,
        row: row,
        col: col
    };

    scene.add(mesh);
    objects.push(mesh);
    console.log('Fallback cube added to scene and array. Total objects now:', objects.length, 'Name:', name);
    initialObjectPositions.set(mesh, position.clone());
    
    // If this is the first object and we're in first-load mode, select it
    if (shouldSelectFirstObject && !firstObjectSelected && objects.length === 1) {
        console.log('First object (fallback cube) loaded! Selecting it.');
        setTimeout(() => selectObjectByIndex(0), 100);
        firstObjectSelected = true;
    }
}

function gridLayout(index) {
    const spacing = 8;
    const row = Math.floor(index / itemsPerRow);
    const col = index % itemsPerRow;

    const offsetX = (itemsPerRow - 1) * spacing / 2;

    return new THREE.Vector3(
        col * spacing - offsetX,
        10 - row * spacing,
        0
    );
}

async function loadObjects() {
    try {
        console.log('Fetching objects from API...');
        const response = await fetch('/api/objects');
        const objectsList = await response.json();
        console.log('Objects received:', objectsList.length, 'items');

        const wasEmpty = objects.length === 0;
        // console.log('Was empty before loading?', wasEmpty, 'Current objects.length:', objects.length);
        
        // Set flag to select first object if this is a fresh load
        if (wasEmpty && objectsList.length > 0) {
            shouldSelectFirstObject = true;
            // console.log('Setting shouldSelectFirstObject flag');
        }

        // Add new objects
        objectsList.forEach((obj, index) => {
            if (!loadedObjectIds.has(obj.id)) {
                const position = gridLayout(index);
                const row = Math.floor(index / itemsPerRow);
                const col = index % itemsPerRow;
                const status = obj.status || 'ready'; // Default to ready for backwards compatibility
                loadObject(obj.name, position, obj.id, obj.size, obj.added, row, col, status);
                loadedObjectIds.add(obj.id);
            }
        });
        // Calculate global stats
        let totalVertexCount = 0;
        let totalFileSize = 0;
        objects.forEach(obj => {
            totalVertexCount += obj.userData.vertexCount;
            totalFileSize += obj.userData.fileSize;
        });

        totalFileSize = Math.round(totalFileSize * 100) / 100; // Round to 2 decimals

        // Update stats
        const statsEl = document.getElementById('stats-global');
        statsEl.innerHTML = `${loadedObjectIds.size} Objects <br>${totalVertexCount} Vertices<br>${totalFileSize} MB`;
        console.log('Total objects:', loadedObjectIds.size);

    } catch (error) {
        console.error('Error loading objects:', error);
    }
}

function onKeyDown(event) {
    let mappedKey = event.key;
    if (customKeyMapping) {
        mappedKey = keyMap[event.key];
    }
    
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(mappedKey)) {
        event.preventDefault();
        const newIndex = getNeighbor(mappedKey);
        if (newIndex !== null && newIndex !== selectedObjectIndex) {
            selectObjectByIndex(newIndex);
        }
    } else if (mappedKey === 'i') {
        event.preventDefault();
        toggleZoom();
    } else if (mappedKey === 'p') {
        event.preventDefault();
        toggleViewMode();
    }
}

function selectObjectByIndex(index) {
    if (index < 0 || index >= objects.length) {
        return;
    }
    
    // Remove highlight from previously selected object
    if (selectedObjectIndex !== null && selectedObjectIndex < objects.length) {
        objects[selectedObjectIndex].traverse((child) => {
            if (child.material) {
                child.material.emissiveIntensity = 0.;
            }
        });
    }
    
    selectedObjectIndex = index;
    const obj = objects[index];
    obj.userData.isSelected = true;
    
    // Update grid coordinates
    selectedRow = obj.userData.row;
    selectedCol = obj.userData.col;
    
    // Add visual highlight to selected object
    obj.traverse((child) => {
        if (child.material) {
            child.material.emissiveIntensity = 0.8;
        }
    });
    
    // Show info panel for the centered object
    showInfoPanel(obj.userData);
}

function toggleZoom() {
    isZoomed = !isZoomed;
    console.log('Zoom toggled:', isZoomed ? 'zoomed in' : 'zoomed out');
}

function deselectObject() {
    if (selectedObjectIndex !== null) {
        objects[selectedObjectIndex].userData.isSelected = false;
        selectedObjectIndex = null;
        closeInfoPanel();
    }
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}



function showInfoPanel(data) {
    const detailsEl = document.getElementById('object-details');
    const panel = document.getElementById('info-panel');
    detailsEl.innerHTML = `${data.name}<br>${data.vertexCount} Vertices<br>${Math.round(data.fileSize * 100) / 100} MB`;
    panel.classList.add('visible');
}

function closeInfoPanel() {
    document.getElementById('info-panel').classList.remove('visible');
}

function animate() {
    requestAnimationFrame(animate);

    // Update physics simulation if enabled
    if (physicsEnabled) {
        physicsWorld.step(1 / 30);
        
        // Sync physics bodies with Three.js objects
        physicsObjects.forEach((body, object) => {
            object.position.copy(body.position);
            object.quaternion.copy(body.quaternion);
        });
    } else {
        // Rotate objects around Y-axis only (in grid mode)
        // Loading objects rotate faster
        objects.forEach(obj => {
            const isLoading = obj.userData.isLoading;
            const rotationSpeed = isLoading ? 0.025 : 0.01; // Faster rotation for loading
            obj.rotation.y += rotationSpeed;
            
            // Add scale pulsing for loading objects
            if (isLoading) {
                const pulse = 0.95 + 0.05 * Math.sin(Date.now() * 0.003);
                obj.scale.set(pulse, pulse, pulse);
            }
        });
    }

    // Handle selected object - move camera in front of it (orthogonally)
    if (selectedObjectIndex !== null && selectedObjectIndex < objects.length) {
        const selectedObject = objects[selectedObjectIndex];
        // Determine distance based on zoom state
        const distance = isZoomed ? zoomDistance : normalDistance;
        // Target position: directly in front of the selected object on Z-axis
        const targetCameraPos = new THREE.Vector3(
            selectedObject.position.x,
            selectedObject.position.y,
            selectedObject.position.z + distance
        );
        camera.position.lerp(targetCameraPos, 0.05);
    } else {
        // Move camera back to centered view
        const targetCameraPos = new THREE.Vector3(0, 0, normalDistance);
        camera.position.lerp(targetCameraPos, 0.05);
    }

    renderer.render(scene, camera);
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
