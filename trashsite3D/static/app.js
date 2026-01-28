import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

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

    // Event Listeners
    window.addEventListener('resize', onWindowResize);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('click', onClick);
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

function loadObject(name, position, id, fileSize, addedTime) {
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
            const scale = 4 / maxDim;

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
                fileSize: (fileSize) / (1024 * 1024) // Convert bytes to MB
            };

            scene.add(model);
            objects.push(model);
        },
        undefined,
        function (error) {
            // GLB failed to load, create fallback cube
            console.log('GLB not found or failed to load for', id, '- using cube fallback');
            createFallbackCube(name, position, id);
        }
    );
}

function createFallbackCube(name, position, id) {
    // Fallback: create a simple cube
    const material = new THREE.MeshPhongMaterial({});


    const geometry = new THREE.BoxGeometry(2, 2, 2);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(position);
    mesh.castShadow = false;
    mesh.receiveShadow = false;
    mesh.material.color = new THREE.Color(0xffffff);
    mesh.material.emissive = new THREE.Color(0x8846fa);
    mesh.material.emissiveIntensity = 0.;

    // Store metadata
    mesh.userData = {
        id: id,
        name: "loading...",
        added: new Date().toLocaleString(),
        gridPosition: position.clone(),
        isSelected: false,
        vertexCount: 0,
        fileSize: 0
    };

    scene.add(mesh);
    objects.push(mesh);
}

function gridLayout(index, itemsPerRow = 7) {
    const spacing = 6.5;
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
                loadObject(obj.name, position, obj.id, obj.size, obj.added);
                loadedObjectIds.add(obj.id);
                console.log('Added object:', obj.name);
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
        statsEl.innerHTML = `${loadedObjectIds.size} Objects <br>${totalVertexCount} vertices<br>${totalFileSize} MB`;
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

function selectObject(obj) {
    // Deselect previous selection
    if (selectedObject) {
        deselectObject();
    }

    selectedObject = obj;
    obj.userData.isSelected = true;
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
        // Reset material and scale for all children (handles both meshes and groups)
        selectedObject.traverse((child) => {
            if (child.material) {
                child.material.emissiveIntensity = 0.;
            }
        });
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

    // Remove highlight from previously hovered object
    if (hoveredObject && hoveredObject !== intersectedRoot) {
        hoveredObject.traverse((child) => {
            if (child.material) {
                child.material.emissiveIntensity = 0.;
            }
        });
    }

    if (intersectedRoot) {
        intersectedRoot.traverse((child) => {
            if (child.material) {
                child.material.emissiveIntensity = 0.5;
            }
        });
        hoveredObject = intersectedRoot;

        // Show info panel
        showInfoPanel(intersectedRoot.userData);
    } else {
        hoveredObject = null;
        closeInfoPanel();
    }
}

function showInfoPanel(data) {
    const nameEl = document.getElementById('object-name');
    const detailsEl = document.getElementById('object-details');
    const panel = document.getElementById('info-panel');

    nameEl.textContent = data.name;
    detailsEl.innerHTML = `${data.added}<br>${data.vertexCount} Vertices<br>${Math.round(data.fileSize * 100) / 100} MB`;

    panel.classList.add('visible');
}

function closeInfoPanel() {
    document.getElementById('info-panel').classList.remove('visible');
}

function animate() {
    requestAnimationFrame(animate);

    checkHover();

    // Handle selected object - move camera in front of it (orthogonally)
    if (selectedObject) {
        // Target position: directly in front of the selected object on Z-axis
        const targetCameraPos = new THREE.Vector3(
            selectedObject.position.x,
            selectedObject.position.y + cameraOffsetY,
            selectedObject.position.z + 10
        );
        camera.position.lerp(targetCameraPos, 0.1);
    } else {
        // Move camera back to base orthogonal position
        const targetCameraPos = new THREE.Vector3(
            0,
            cameraOffsetY,
            35
        );
        camera.position.lerp(targetCameraPos, 0.1);
    }

    // Rotate objects around Y-axis only
    objects.forEach(obj => {
        obj.rotation.y += 0.003;
    });

    renderer.render(scene, camera);
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
