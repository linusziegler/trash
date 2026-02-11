import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as CANNON from 'cannon';

// Three.js Scene Setup
let scene, camera, renderer;
let objects = [];
let raycaster = new THREE.Raycaster();
let mouse = new THREE.Vector2();
let hoveredObject = null;
let selectedObject = null;
let loadedObjectIds = new Set();
let cameraBasePos = new THREE.Vector3(0, 15, 25);
let cameraOffsetY = 0;
let gltfLoader = new GLTFLoader();

const itemsPerRow = 8;

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
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('click', onClick);
    document.addEventListener('wheel', onScroll);
    
    // View toggle buttons
    document.getElementById('grid-btn').addEventListener('click', () => {
        if (currentViewMode !== 'grid') switchToGridView();
    });
    document.getElementById('pile-btn').addEventListener('click', () => {
        if (currentViewMode !== 'pile') switchToPileView();
    });
    console.log('Event listeners added');

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
    floorBody.position.y = -30;
    physicsWorld.addBody(floorBody);
    
    console.log('Physics world initialized');
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
    
    // Create physics bodies for all objects
    objects.forEach(obj => {
        createPhysicsBody(obj);
    });
    
    // Update button styling
    document.getElementById('grid-btn').classList.remove('active');
    document.getElementById('pile-btn').classList.add('active');
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
    
    // Update button styling
    document.getElementById('grid-btn').classList.add('active');
    document.getElementById('pile-btn').classList.remove('active');
}

function toggleViewMode() {
    if (currentViewMode === 'grid') {
        switchToPileView();
    } else {
        switchToGridView();
    }
}

function loadObject(name, position, id, fileSize, addedTime, status = 'ready') {
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

            // Store metadata
            model.userData = {
                id: id,
                name: name,
                added: new Date(addedTime).toLocaleString(),
                gridPosition: position.clone(),
                isSelected: false,
                vertexCount: vertexCount,
                fileSize: (fileSize) / (1024 * 1024), // Convert bytes to MB
                status: 'ready',
                isLoading: false
            };

            scene.add(model);
            objects.push(model);
            initialObjectPositions.set(model, position.clone());
        },
        undefined,
        function (error) {
            // GLB failed to load, create fallback cube
            console.log('GLB not found or failed to load for', id, '- using cube fallback');
            createFallbackCube(name, position, id, status);
        }
    );
}

function createFallbackCube(name, position, id, status = 'ready') {
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

    // Store metadata
    mesh.userData = {
        id: id,
        name: isLoading ? "loading..." : name,
        added: new Date().toLocaleString(),
        gridPosition: position.clone(),
        isSelected: false,
        vertexCount: 0,
        fileSize: 0,
        status: status,
        isLoading: isLoading
    };

    scene.add(mesh);
    objects.push(mesh);
    initialObjectPositions.set(mesh, position.clone());
}

function gridLayout(index) {
    const spacing = 6.2;
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
        console.log('Objects received:', objectsList);

        // Add new objects
        objectsList.forEach((obj, index) => {
            if (!loadedObjectIds.has(obj.id)) {
                const position = gridLayout(index);
                const status = obj.status || 'ready'; // Default to ready for backwards compatibility
                loadObject(obj.name, position, obj.id, obj.size, obj.added, status);
                loadedObjectIds.add(obj.id);
                console.log('Added object:', obj.name, 'Status:', status);
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

function onMouseMove(event) {
    // Update mouse position for raycasting
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

    // draw circle around mouse
    const circle = document.getElementById('mouse-circle');
    circle.style.left = `${event.clientX}px`;
    circle.style.top = `${event.clientY}px`;
    
    // Check hover on mousemove
    checkHover();
}

function onClick(event) {
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(objects, true);

    if (intersects.length > 0) {
        let clickedObject = intersects[0].object;
        // Traverse up to find the root object in the objects array
        while (clickedObject.parent && !objects.includes(clickedObject)) {
            clickedObject = clickedObject.parent;
        }
        if (selectedObject === clickedObject) {
            // Deselect if clicking the same object
            deselectObject();
        } else {
            // Select new object
            selectObject(clickedObject);
        }
    } else {
        // Deselect if clicking empty space
        deselectObject();
    }
}

// implement scroll logic to move camera up and down
function onScroll(event) {
    cameraOffsetY -= event.deltaY * 0.03;
    // Limit cameraOffsetY to reasonable bounds based on number of objects
    let maxOffset = -4 * ((loadedObjectIds.size / itemsPerRow) - 1); // Adjust based on number of rows
    cameraOffsetY = Math.max(maxOffset, Math.min(0, cameraOffsetY));
}

function selectObject(obj) {
    // Deselect previous selection
    if (selectedObject) {
        deselectObject();
    }

    selectedObject = obj;
    obj.userData.isSelected = true;
    
    // Remove emissive effect when object is selected
    obj.traverse((child) => {
        if (child.material) {
            child.material.emissiveIntensity = 0.;
        }
    });
    
    // Show info panel and keep it visible
    showInfoPanel(obj.userData);
}

function deselectObject() {
    if (selectedObject) {
        selectedObject.userData.isSelected = false;
        selectedObject = null;
        closeInfoPanel();
    }
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function checkHover() {
    // Skip hover checks if an object is selected
    if (selectedObject) {
        return;
    }

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(objects, true);

    // Find root object from intersected child
    let intersectedRoot = null;
    if (intersects.length > 0) {
        let obj = intersects[0].object;
        while (obj.parent && !objects.includes(obj)) {
            obj = obj.parent;
        }
        intersectedRoot = objects.includes(obj) ? obj : null;
    }

    // Only update materials if hovered object changed
    if (hoveredObject !== intersectedRoot) {
        // Remove highlight from previously hovered object
        if (hoveredObject) {
            hoveredObject.traverse((child) => {
                if (child.material) {
                    child.material.emissiveIntensity = 0.;
                }
            });
        }

        // Highlight new hovered object
        if (intersectedRoot) {
            intersectedRoot.traverse((child) => {
                if (child.material) {
                    child.material.emissiveIntensity = 0.5;
                }
            });
            showInfoPanel(intersectedRoot.userData);
        } else {
            closeInfoPanel();
        }

        hoveredObject = intersectedRoot;
    }
}

function showInfoPanel(data) {
    const detailsEl = document.getElementById('object-details');
    const panel = document.getElementById('info-panel');
    // detailsEl.innerHTML = `${data.added}<br>${data.vertexCount} Vertices<br>${Math.round(data.fileSize * 100) / 100} MB`;
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
    if (selectedObject) {
        // Target position: directly in front of the selected object on Z-axis
        const targetCameraPos = new THREE.Vector3(
            selectedObject.position.x,
            selectedObject.position.y,
            selectedObject.position.z + 8
        );
        camera.position.lerp(targetCameraPos, 0.05);
    } else {
        // Move camera back to base orthogonal position
        const targetCameraPos = new THREE.Vector3(
            0,
            cameraOffsetY,
            35
        );
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
