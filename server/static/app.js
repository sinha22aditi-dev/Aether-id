/**
 * AETHER.ID // Front-End Application Controller & Three.js 3D Visualizer
 */

// =============================================================================
// 1. Three.js Interactive 3D Visualizer (Aether3DScene)
// =============================================================================
class Aether3DScene {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas || typeof THREE === "undefined") {
      console.warn("Three.js not loaded or canvas missing. 3D visualizer operating in fallback mode.");
      return;
    }

    try {
      this.init();
      this.animate();
    } catch (e) {
      console.warn("WebGL initialization fallback:", e);
    }
  }

  init() {
    this.scene = new THREE.Scene();
    
    const width = this.canvas.clientWidth || 400;
    const height = this.canvas.clientHeight || 220;
    
    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    this.camera.position.z = 18;

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: true
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    this.scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0x14b8a6, 1.2);
    dirLight.position.set(10, 20, 15);
    this.scene.add(dirLight);

    const pointLight = new THREE.PointLight(0x06b6d4, 1.5, 50);
    pointLight.position.set(-10, -10, 10);
    this.scene.add(pointLight);

    // Group Container
    this.containerGroup = new THREE.Group();
    this.scene.add(this.containerGroup);

    // 1. Central Biometric Face Mesh Abstraction (Icosahedron Wireframe + Vertices)
    const meshGeo = new THREE.IcosahedronGeometry(4, 2);
    const meshMat = new THREE.MeshStandardMaterial({
      color: 0x14b8a6,
      wireframe: true,
      transparent: true,
      opacity: 0.35,
      roughness: 0.2,
      metalness: 0.8
    });
    this.faceMesh = new THREE.Mesh(meshGeo, meshMat);
    this.containerGroup.add(this.faceMesh);

    // Landmark Vertices Points
    const ptsMat = new THREE.PointsMaterial({
      color: 0x06b6d4,
      size: 0.25,
      transparent: true,
      opacity: 0.7
    });
    this.landmarkPoints = new THREE.Points(meshGeo, ptsMat);
    this.containerGroup.add(this.landmarkPoints);

    // 2. Satellite Search & Candidate Nodes
    this.satelliteGroup = new THREE.Group();
    this.satellites = [];
    const satCount = 8;
    for (let i = 0; i < satCount; i++) {
      const angle = (i / satCount) * Math.PI * 2;
      const radius = 9;
      const satGeo = new THREE.SphereGeometry(0.35, 16, 16);
      const satMat = new THREE.MeshStandardMaterial({
        color: 0x3b82f6,
        emissive: 0x1e3a8a,
        transparent: true,
        opacity: 0.5
      });
      const sat = new THREE.Mesh(satGeo, satMat);
      sat.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius, (Math.random() - 0.5) * 3);
      this.satellites.push(sat);
      this.satelliteGroup.add(sat);
    }
    this.containerGroup.add(this.satelliteGroup);

    // 3. Blockchain Cubes Chain (Hidden by default, shown during HASH / COMMIT)
    this.blockChainGroup = new THREE.Group();
    this.blocks = [];
    for (let i = 0; i < 4; i++) {
      const blockGeo = new THREE.BoxGeometry(1.6, 1.6, 1.6);
      const blockMat = new THREE.MeshStandardMaterial({
        color: 0x10b981,
        wireframe: false,
        transparent: true,
        opacity: 0.05
      });
      const block = new THREE.Mesh(blockGeo, blockMat);
      block.position.set((i - 1.5) * 2.8, -6, 0);
      this.blocks.push(block);
      this.blockChainGroup.add(block);
    }
    this.containerGroup.add(this.blockChainGroup);

    // Dynamic State Settings
    this.currentStage = "IDLE";
    this.targetRotationSpeed = 0.003;
    this.targetPulseSpeed = 1.0;

    // Handle Window Resize
    window.addEventListener("resize", () => this.onResize());
  }

  onResize() {
    if (!this.renderer || !this.camera) return;
    const width = this.canvas.clientWidth || 400;
    const height = this.canvas.clientHeight || 220;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  setStage(stage) {
    this.currentStage = stage;
    const stageLabel = document.getElementById("scene-stage-label");

    if (stageLabel) {
      stageLabel.textContent = `STATE: ${stage}`;
    }

    if (!this.faceMesh) return;

    switch (stage) {
      case "SCAN":
      case "ENCODE":
        this.targetRotationSpeed = 0.012;
        this.faceMesh.material.color.setHex(0x06b6d4);
        this.faceMesh.material.opacity = 0.6;
        this.landmarkPoints.material.color.setHex(0x14b8a6);
        this.landmarkPoints.material.size = 0.4;
        break;

      case "SEARCH":
        this.targetRotationSpeed = 0.02;
        this.satelliteGroup.children.forEach(sat => {
          sat.material.color.setHex(0x3b82f6);
          sat.material.opacity = 0.9;
        });
        break;

      case "MATCH":
        this.targetRotationSpeed = 0.008;
        this.faceMesh.material.color.setHex(0x10b981);
        this.faceMesh.material.opacity = 0.7;
        if (this.satellites[0]) {
          this.satellites[0].material.color.setHex(0x10b981);
          this.satellites[0].scale.set(1.8, 1.8, 1.8);
        }
        break;

      case "HASH":
      case "COMMIT":
        this.targetRotationSpeed = 0.005;
        this.blocks.forEach(b => {
          b.material.opacity = 0.85;
          b.material.color.setHex(0x10b981);
        });
        break;

      case "VERIFIED":
        this.targetRotationSpeed = 0.003;
        this.faceMesh.material.color.setHex(0x14b8a6);
        this.faceMesh.material.opacity = 0.45;
        this.blocks.forEach(b => {
          b.material.opacity = 0.9;
          b.material.color.setHex(0x10b981);
        });
        break;

      case "IDLE":
      default:
        this.targetRotationSpeed = 0.003;
        this.faceMesh.material.color.setHex(0x14b8a6);
        this.faceMesh.material.opacity = 0.35;
        this.landmarkPoints.material.size = 0.25;
        this.satellites.forEach(s => s.scale.set(1, 1, 1));
        this.blocks.forEach(b => b.material.opacity = 0.05);
        break;
    }
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    if (!this.renderer || !this.scene || !this.camera) return;

    const time = Date.now() * 0.001;

    // Smooth rotation
    this.containerGroup.rotation.y += this.targetRotationSpeed;
    this.containerGroup.rotation.x = Math.sin(time * 0.5) * 0.1;

    // Floating animation
    this.faceMesh.position.y = Math.sin(time * 1.5) * 0.2;
    this.satelliteGroup.rotation.z += 0.005;

    // Block chain rotation
    this.blocks.forEach((block, idx) => {
      block.rotation.x += 0.01;
      block.rotation.y += 0.01;
    });

    this.renderer.render(this.scene, this.camera);
  }
}

// =============================================================================
// 2. Application UI Controller
// =============================================================================
document.addEventListener("DOMContentLoaded", () => {
  let selectedFile = null;
  let webcamStream = null;
  let aetherScene = null;

  // Initialize 3D Scene
  aetherScene = new Aether3DScene("aether-3d-viewport");

  // DOM Elements
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");
  
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const imagePreview = document.getElementById("image-preview");
  const dropPrompt = document.getElementById("drop-prompt");
  const webcamBtn = document.getElementById("webcam-btn");
  const clearBtn = document.getElementById("clear-btn");
  const webcamBox = document.getElementById("webcam-box");
  const webcamVideo = document.getElementById("webcam-video");
  const snapBtn = document.getElementById("snap-btn");
  const runPipelineBtn = document.getElementById("run-pipeline-btn");

  const toggleOptionsBtn = document.getElementById("toggle-options-btn");
  const optionsContent = document.getElementById("options-content");
  const toggleLogsBtn = document.getElementById("toggle-logs-btn");
  const logsContent = document.getElementById("logs-content");
  const logsList = document.getElementById("logs-list");

  const rpcDot = document.getElementById("rpc-dot");
  const rpcText = document.getElementById("rpc-text");
  const rpcStatusIndicator = document.getElementById("rpc-status-indicator");
  const openDiagBtn = document.getElementById("open-diag-btn");
  const closeDiagBtn = document.getElementById("close-diag-btn");
  const diagModal = document.getElementById("diag-modal");
  const diagModalBody = document.getElementById("diag-modal-body");

  // Telemetry & Results
  const pipelineStatusBadge = document.getElementById("pipeline-status-badge");
  const faceTelemetryBar = document.getElementById("face-telemetry-bar");
  const telemetryCropImg = document.getElementById("telemetry-crop-img");
  const telFaces = document.getElementById("tel-faces");
  const telBox = document.getElementById("tel-box");
  const telBlur = document.getElementById("tel-blur");

  const resultsWrapper = document.getElementById("results-wrapper");
  const resRecordId = document.getElementById("res-record-id");
  const resTxHash = document.getElementById("res-tx-hash");
  const resExplorerLink = document.getElementById("res-explorer-link");
  const resSourceBadge = document.getElementById("res-source-badge");
  const winnerImg = document.getElementById("winner-img");
  const winnerTitle = document.getElementById("winner-title");
  const winnerPlatform = document.getElementById("winner-platform");
  const winnerSimText = document.getElementById("winner-sim-text");
  const winnerSimFill = document.getElementById("winner-sim-fill");
  const winnerUrlBtn = document.getElementById("winner-url-btn");
  const verifyWinnerBtn = document.getElementById("verify-winner-btn");
  const resContentHash = document.getElementById("res-content-hash");
  const codeTierA = document.getElementById("code-tier-a");
  const codeTierB = document.getElementById("code-tier-b");
  const btnJsonTierA = document.getElementById("btn-json-tier-a");
  const btnJsonTierB = document.getElementById("btn-json-tier-b");
  const candidateGrid = document.getElementById("candidate-grid");
  const candidateCountBadge = document.getElementById("candidate-count-badge");

  // Verification Sandbox Elements
  const verifyRecordId = document.getElementById("verify-record-id");
  const verifyJsonPayload = document.getElementById("verify-json-payload");
  const verifyLiveCheck = document.getElementById("verify-live-check");
  const executeVerifyBtn = document.getElementById("execute-verify-btn");
  const actionVerifyOrig = document.getElementById("action-verify-orig");
  const actionVerifyTamper = document.getElementById("action-verify-tamper");
  const actionVerifyUnknown = document.getElementById("action-verify-unknown");
  
  const verifyOutputBox = document.getElementById("verify-output-box");
  const verifyBanner = document.getElementById("verify-banner");
  const vStatusIcon = document.getElementById("v-status-icon");
  const vStatusTitle = document.getElementById("v-status-title");
  const vStatusMsg = document.getElementById("v-status-msg");
  const vComputedHash = document.getElementById("v-computed-hash");
  const vOnchainHash = document.getElementById("v-onchain-hash");
  const vHashMatch = document.getElementById("v-hash-match");
  const vSourceReachable = document.getElementById("v-source-reachable");
  const vSubmitter = document.getElementById("v-submitter");
  const vTimestamp = document.getElementById("v-timestamp");
  const vUri = document.getElementById("v-uri");
  const tamperAnalysisBox = document.getElementById("tamper-analysis-box");
  const tamperTableBody = document.getElementById("tamper-table-body");

  // Audit Ledger Elements
  const recordsTableBody = document.getElementById("records-table-body");
  const refreshRecordsBtn = document.getElementById("refresh-records-btn");

  // ---------------------------------------------------------------------------
  // 1. Fetch & Display System / Blockchain Status
  // ---------------------------------------------------------------------------
  async function fetchStatus() {
    try {
      const resp = await fetch("/api/status");
      if (resp.ok) {
        const data = await resp.json();
        const bc = data.blockchain;
        
        if (bc.connected) {
          rpcDot.className = "status-dot dot-teal";
          if (bc.use_local_chain) {
            rpcText.textContent = "Local EVM Connected";
          } else {
            const bal = bc.wallet_balance_pol !== null ? `${bc.wallet_balance_pol.toFixed(3)} POL` : "";
            rpcText.textContent = `Polygon Amoy (${bc.status}) ${bal}`.trim();
          }
          rpcStatusIndicator.title = bc.summary || "Blockchain connected cleanly";
        } else {
          rpcDot.className = "status-dot dot-amber";
          rpcText.textContent = "RPC Pending";
          rpcStatusIndicator.title = bc.summary || "Connecting to RPC endpoint...";
        }
      }
    } catch (e) {
      console.warn("Could not fetch status:", e);
    }
  }
  fetchStatus();

  // Diagnostics Modal
  async function showDiagnostics() {
    diagModal.style.display = "flex";
    diagModalBody.innerHTML = "<p class='dim'>Fetching deep blockchain diagnostics...</p>";
    try {
      const resp = await fetch("/api/blockchain/diagnostics");
      const diag = await resp.json();
      diagModalBody.innerHTML = `
        <div class="metric-row"><span class="m-label">RPC Status:</span> <strong>${diag.status}</strong></div>
        <div class="metric-row"><span class="m-label">Active RPC Endpoint:</span> <span class="mono">${diag.active_rpc_url || 'None'}</span></div>
        <div class="metric-row"><span class="m-label">Chain ID:</span> <span class="mono">${diag.actual_chain_id || diag.expected_chain_id}</span></div>
        <div class="metric-row"><span class="m-label">Block Number:</span> <span class="mono">${diag.block_number || 'N/A'}</span></div>
        <div class="metric-row"><span class="m-label">Contract Address:</span> <span class="mono">${diag.contract.address}</span></div>
        <div class="metric-row"><span class="m-label">Contract Deployed:</span> <strong>${diag.contract.deployed ? 'YES' : 'NO'}</strong></div>
        <div class="metric-row"><span class="m-label">Wallet Address:</span> <span class="mono">${diag.wallet.address}</span></div>
        <div class="metric-row"><span class="m-label">Wallet POL Balance:</span> <strong>${diag.wallet.balance_pol !== null ? diag.wallet.balance_pol.toFixed(4) + ' POL' : 'N/A'}</strong></div>
        <div style="margin-top: 1rem; font-size: 0.8rem; color: var(--text-sub);">${diag.summary}</div>
      `;
    } catch (e) {
      diagModalBody.innerHTML = `<p class="text-red">Error fetching diagnostics: ${e.message}</p>`;
    }
  }

  if (openDiagBtn) openDiagBtn.addEventListener("click", showDiagnostics);
  if (closeDiagBtn) closeDiagBtn.addEventListener("click", () => diagModal.style.display = "none");

  // ---------------------------------------------------------------------------
  // 2. Navigation Tabs
  // ---------------------------------------------------------------------------
  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      tabButtons.forEach(b => b.classList.remove("active"));
      tabPanels.forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      document.getElementById(targetId).classList.add("active");

      if (targetId === "tab-records") {
        fetchAuditRecords();
      }
    });
  });

  // Accordions
  if (toggleOptionsBtn) {
    toggleOptionsBtn.addEventListener("click", () => {
      const isHidden = optionsContent.style.display === "none";
      optionsContent.style.display = isHidden ? "block" : "none";
      toggleOptionsBtn.querySelector(".arrow-icon").textContent = isHidden ? "▲" : "▼";
    });
  }

  if (toggleLogsBtn) {
    toggleLogsBtn.addEventListener("click", () => {
      const isHidden = logsContent.style.display === "none";
      logsContent.style.display = isHidden ? "block" : "none";
      toggleLogsBtn.querySelector(".arrow-icon").textContent = isHidden ? "▲" : "▼";
    });
  }

  // ---------------------------------------------------------------------------
  // 3. File Input & Camera
  // ---------------------------------------------------------------------------
  dropZone.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      handleSelectedFile(e.target.files[0]);
    }
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("drag-over");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleSelectedFile(e.dataTransfer.files[0]);
    }
  });

  function handleSelectedFile(file) {
    selectedFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      imagePreview.src = e.target.result;
      imagePreview.style.display = "block";
      dropPrompt.style.display = "none";
      clearBtn.style.display = "inline-flex";
      runPipelineBtn.disabled = false;
    };
    reader.readAsDataURL(file);
  }

  clearBtn.addEventListener("click", () => {
    selectedFile = null;
    fileInput.value = "";
    imagePreview.src = "";
    imagePreview.style.display = "none";
    dropPrompt.style.display = "flex";
    clearBtn.style.display = "none";
    runPipelineBtn.disabled = true;
    if (webcamStream) stopWebcam();
  });

  webcamBtn.addEventListener("click", async () => {
    try {
      webcamBox.style.display = "block";
      webcamStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
      webcamVideo.srcObject = webcamStream;
    } catch (e) {
      alert("Unable to access webcam: " + e.message);
    }
  });

  snapBtn.addEventListener("click", () => {
    const canvas = document.createElement("canvas");
    canvas.width = webcamVideo.videoWidth || 640;
    canvas.height = webcamVideo.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(webcamVideo, 0, 0, canvas.width, canvas.height);

    canvas.toBlob((blob) => {
      selectedFile = new File([blob], "camera_snap.jpg", { type: "image/jpeg" });
      imagePreview.src = canvas.toDataURL("image/jpeg");
      imagePreview.style.display = "block";
      dropPrompt.style.display = "none";
      clearBtn.style.display = "inline-flex";
      runPipelineBtn.disabled = false;
      stopWebcam();
    }, "image/jpeg", 0.95);
  });

  function stopWebcam() {
    if (webcamStream) {
      webcamStream.getTracks().forEach(track => track.stop());
      webcamStream = null;
    }
    webcamBox.style.display = "none";
  }

  // ---------------------------------------------------------------------------
  // 4. Pipeline Execution & 3D Stage Transitions
  // ---------------------------------------------------------------------------
  const stageMap = {
    "stage-detect": "SCAN",
    "stage-embed": "ENCODE",
    "stage-search": "SEARCH",
    "stage-match": "MATCH",
    "stage-canon": "HASH",
    "stage-chain": "COMMIT",
  };

  function updateStageUI(stageId, state) {
    const stepEl = document.getElementById(stageId);
    if (!stepEl) return;

    if (state === "active") {
      stepEl.className = "stage-step active";
      if (aetherScene) aetherScene.setStage(stageMap[stageId] || "IDLE");
    } else if (state === "completed") {
      stepEl.className = "stage-step completed";
      const line = stepEl.nextElementSibling;
      if (line && line.classList.contains("stage-line")) {
        line.classList.add("completed");
      }
    } else {
      stepEl.className = "stage-step";
    }
  }

  function resetStageFlow() {
    Object.keys(stageMap).forEach(id => updateStageUI(id, "idle"));
    document.querySelectorAll(".stage-line").forEach(l => l.classList.remove("completed"));
    resultsWrapper.style.display = "none";
    faceTelemetryBar.style.display = "none";
    logsList.innerHTML = "";
    if (aetherScene) aetherScene.setStage("IDLE");
  }

  runPipelineBtn.addEventListener("click", async () => {
    if (!selectedFile) return;

    resetStageFlow();
    runPipelineBtn.disabled = true;
    runPipelineBtn.textContent = "⚙️ Executing Pipeline...";
    pipelineStatusBadge.textContent = "RUNNING";
    pipelineStatusBadge.className = "badge badge-teal";

    updateStageUI("stage-detect", "active");

    const formData = new FormData();
    formData.append("file", selectedFile);

    const thresh = document.getElementById("threshold-input").value;
    if (thresh) formData.append("threshold", thresh);

    const faceIdx = document.getElementById("face-index-input").value;
    if (faceIdx) formData.append("face_index", faceIdx);

    const dryRun = document.getElementById("dry-run-checkbox").checked;
    formData.append("dry_run", dryRun);

    try {
      // Simulate visual stage progression
      setTimeout(() => updateStageUI("stage-embed", "active"), 400);
      setTimeout(() => updateStageUI("stage-search", "active"), 900);

      const resp = await fetch("/api/scan", {
        method: "POST",
        body: formData,
      });

      const data = await resp.json();

      // Render logs
      if (data.logs) {
        logsList.innerHTML = "";
        data.logs.forEach(l => {
          const row = document.createElement("div");
          row.className = "log-row";
          row.textContent = `[${l.step}] ${l.status} (${l.duration_ms}ms) - ${l.details}`;
          logsList.appendChild(row);
        });
      }

      // Show face crop telemetry
      if (data.detection && data.detection.crop_image_b64) {
        telemetryCropImg.src = data.detection.crop_image_b64;
        telFaces.textContent = data.detection.total_faces;
        telBox.textContent = data.detection.box ? `[${data.detection.box.join(", ")}]` : "--";
        telBlur.textContent = `${data.detection.blur_score} (${data.detection.is_blurry ? "Blurry" : "Sharp"})`;
        faceTelemetryBar.style.display = "flex";
      }

      if (data.status === "SUCCESS") {
        updateStageUI("stage-match", "active");
        updateStageUI("stage-canon", "active");
        updateStageUI("stage-chain", "completed");
        
        if (aetherScene) aetherScene.setStage("VERIFIED");

        pipelineStatusBadge.textContent = "COMPLETED";
        pipelineStatusBadge.className = "badge badge-emerald";

        // Fill blockchain result banner
        if (data.blockchain) {
          resRecordId.textContent = `#${data.blockchain.record_id}`;
          resTxHash.textContent = data.blockchain.tx_hash;
          resExplorerLink.href = data.blockchain.explorer_url || "#";
          document.getElementById("flow-record-id-sub").textContent = `Record #${data.blockchain.record_id}`;
        }

        // Fill winner match details
        if (data.candidates && data.candidates.length > 0) {
          const winner = data.candidates[0];
          winnerTitle.textContent = winner.title || winner.url;
          winnerPlatform.textContent = `Platform: ${winner.platform} (${data.immutable_data?.source_type || 'SOCIAL_MEDIA'})`;
          resSourceBadge.textContent = data.immutable_data?.source_type || 'SOCIAL_MEDIA';
          
          const simPct = (winner.similarity_score * 100).toFixed(1);
          winnerSimText.textContent = `${simPct}%`;
          winnerSimFill.style.width = `${simPct}%`;
          
          winnerImg.src = winner.image_b64 || '/static/placeholder.jpg';
          winnerUrlBtn.href = winner.url;

          verifyWinnerBtn.onclick = () => {
            verifyRecordId.value = data.blockchain ? data.blockchain.record_id : 0;
            verifyJsonPayload.value = JSON.stringify(data.immutable_data, null, 2);
            document.querySelector('[data-tab="tab-verify"]').click();
          };
        }

        // Fill candidate grid
        candidateGrid.innerHTML = "";
        candidateCountBadge.textContent = `${data.candidates ? data.candidates.length : 0} Candidates Evaluated`;
        if (data.candidates) {
          data.candidates.forEach(c => {
            const card = document.createElement("div");
            card.className = `cand-card ${c.rank === 1 ? 'is-winner' : ''}`;
            card.innerHTML = `
              <div class="cand-header">
                <span class="highlight-teal">RANK #${c.rank} ${c.rank === 1 ? '★ WINNER' : ''}</span>
                <span class="mono text-emerald">${(c.similarity_score * 100).toFixed(1)}%</span>
              </div>
              <div class="cand-img-wrap">
                <img src="${c.image_b64 || '/static/placeholder.jpg'}" alt="Candidate">
              </div>
              <div class="cand-title">${c.title || c.url}</div>
              <a href="${c.url}" target="_blank" class="cand-link">${c.url}</a>
            `;
            candidateGrid.appendChild(card);
          });
        }

        // Fill Two-Tier Data
        codeTierA.textContent = JSON.stringify(data.immutable_data, null, 2);
        codeTierB.textContent = JSON.stringify(data.audit_metadata, null, 2);
        resContentHash.textContent = data.content_hash || "0x...";

        resultsWrapper.style.display = "block";

        // Pre-fill verification sandbox
        if (data.blockchain) {
          verifyRecordId.value = data.blockchain.record_id;
          verifyJsonPayload.value = JSON.stringify(data.immutable_data, null, 2);
        }

      } else {
        if (aetherScene) aetherScene.setStage("IDLE");
        pipelineStatusBadge.textContent = data.status;
        pipelineStatusBadge.className = "badge badge-amber";
        alert(`Pipeline result: ${data.status} - ${data.error_message || 'No candidate match satisfied criteria.'}`);
      }

    } catch (e) {
      if (aetherScene) aetherScene.setStage("IDLE");
      alert("Pipeline Request Failure: " + e.message);
      pipelineStatusBadge.textContent = "ERROR";
      pipelineStatusBadge.className = "badge badge-amber";
    } finally {
      runPipelineBtn.disabled = false;
      runPipelineBtn.textContent = "⚡ Run Verification Pipeline";
    }
  });

  // JSON Tier Tabs
  if (btnJsonTierA && btnJsonTierB) {
    btnJsonTierA.addEventListener("click", () => {
      btnJsonTierA.classList.add("active");
      btnJsonTierB.classList.remove("active");
      codeTierA.parentElement.style.display = "block";
      codeTierB.parentElement.style.display = "none";
    });
    btnJsonTierB.addEventListener("click", () => {
      btnJsonTierB.classList.add("active");
      btnJsonTierA.classList.remove("active");
      codeTierB.parentElement.style.display = "block";
      codeTierA.parentElement.style.display = "none";
    });
  }

  // ---------------------------------------------------------------------------
  // 5. Independent Verification Sandbox Controller
  // ---------------------------------------------------------------------------
  actionVerifyOrig.addEventListener("click", async () => {
    const recId = parseInt(verifyRecordId.value, 10);
    try {
      const resp = await fetch("/api/records");
      const records = await resp.json();
      const match = records.find(r => r.record_id === recId);
      if (match) {
        verifyJsonPayload.value = JSON.stringify(match.immutable_data, null, 2);
      } else {
        alert(`Record #${recId} not found in local cache.`);
      }
    } catch (e) {
      alert("Cache retrieval error: " + e.message);
    }
  });

  actionVerifyTamper.addEventListener("click", () => {
    try {
      let data = {};
      if (verifyJsonPayload.value.trim()) {
        data = JSON.parse(verifyJsonPayload.value);
      } else {
        data = {
          "normalized_source_url": "https://twitter.com/user/status/123",
          "platform": "twitter",
          "source_type": "SOCIAL_MEDIA",
          "public_post_id": "123",
          "post_text_normalized": "Verified Portrait of Subject",
          "image_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
          "schema_version": "2.0"
        };
      }
      data.post_text_normalized = "ALTERED text payload attempting unauthorized modification";
      verifyJsonPayload.value = JSON.stringify(data, null, 2);
      alert("Injected tampered field into payload! Click 'Execute Verification Check' to test tamper detection.");
    } catch (e) {
      alert("Invalid JSON in payload.");
    }
  });

  actionVerifyUnknown.addEventListener("click", () => {
    verifyRecordId.value = 99999;
    alert("Set Target Record ID to #99999 (Nonexistent). Click 'Execute Verification Check' to verify RECORD_NOT_FOUND outcome.");
  });

  executeVerifyBtn.addEventListener("click", async () => {
    const recId = parseInt(verifyRecordId.value, 10);
    let payload = {};
    try {
      if (verifyJsonPayload.value.trim()) {
        payload = JSON.parse(verifyJsonPayload.value);
      }
    } catch (e) {
      alert("Invalid JSON payload: " + e.message);
      return;
    }

    executeVerifyBtn.disabled = true;
    executeVerifyBtn.textContent = "🔍 Checking On-Chain Record...";

    try {
      const resp = await fetch("/api/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_id: recId,
          data: payload,
          check_live_source: verifyLiveCheck.checked,
        }),
      });

      const res = await resp.json();

      verifyOutputBox.style.display = "block";
      vStatusTitle.textContent = res.status;
      vStatusMsg.textContent = res.message;

      if (res.status === "VERIFIED") {
        verifyBanner.className = "result-banner";
        vStatusIcon.textContent = "✓";
      } else if (res.status === "TAMPER DETECTED") {
        verifyBanner.className = "result-banner";
        verifyBanner.style.borderColor = "rgba(239, 68, 68, 0.4)";
        verifyBanner.style.background = "rgba(239, 68, 68, 0.1)";
        vStatusIcon.textContent = "✕";
      } else {
        verifyBanner.className = "result-banner";
        verifyBanner.style.borderColor = "rgba(245, 158, 11, 0.4)";
        verifyBanner.style.background = "rgba(245, 158, 11, 0.1)";
        vStatusIcon.textContent = "❓";
      }

      vComputedHash.textContent = res.computed_hash || "N/A";
      vOnchainHash.textContent = res.on_chain_hash || "N/A";
      vHashMatch.textContent = res.is_hash_match ? "YES (Match)" : "NO (Mismatch)";
      vHashMatch.className = res.is_hash_match ? "m-val text-emerald" : "m-val text-red";
      vSourceReachable.textContent = res.source_url_reachable ? "YES (Reachable)" : "NO / Unreachable";

      if (res.on_chain_record && res.on_chain_record.exists) {
        vSubmitter.textContent = res.on_chain_record.submitter;
        vTimestamp.textContent = new Date(res.on_chain_record.timestamp * 1000).toLocaleString();
        vUri.textContent = res.on_chain_record.metadata_uri;
      } else {
        vSubmitter.textContent = "Non-existent";
        vTimestamp.textContent = "N/A";
        vUri.textContent = "N/A";
      }

      // Tamper diffs table
      if (res.field_diffs && res.field_diffs.length > 0) {
        tamperAnalysisBox.style.display = "block";
        tamperTableBody.innerHTML = "";
        res.field_diffs.forEach(d => {
          const row = document.createElement("tr");
          row.innerHTML = `
            <td class="text-amber">${d.field}</td>
            <td class="text-emerald mono">${d.original}</td>
            <td class="text-red mono">${d.tampered}</td>
          `;
          tamperTableBody.appendChild(row);
        });
      } else {
        tamperAnalysisBox.style.display = "none";
      }

    } catch (e) {
      alert("Verification Error: " + e.message);
    } finally {
      executeVerifyBtn.disabled = false;
      executeVerifyBtn.textContent = "🔍 Execute Verification Check";
    }
  });

  // ---------------------------------------------------------------------------
  // 6. Audit Ledger Table
  // ---------------------------------------------------------------------------
  async function fetchAuditRecords() {
    try {
      const resp = await fetch("/api/records");
      const records = await resp.json();
      recordsTableBody.innerHTML = "";

      if (records.length === 0) {
        recordsTableBody.innerHTML = `<tr><td colspan="6" class="text-center dim">No audit records registered yet.</td></tr>`;
        return;
      }

      records.forEach(r => {
        const row = document.createElement("tr");
        const imm = r.immutable_data || {};
        row.innerHTML = `
          <td><strong class="highlight-teal">#${r.record_id}</strong></td>
          <td><span class="badge badge-violet">${imm.source_type || 'SOCIAL_MEDIA'} (${imm.platform || 'web'})</span></td>
          <td class="mono" style="font-size: 0.78rem;">${r.content_hash.slice(0, 16)}...</td>
          <td class="mono" style="font-size: 0.78rem;">${r.tx_hash.slice(0, 16)}...</td>
          <td style="font-size: 0.78rem;" class="text-dim">${new Date(r.created_at).toLocaleString()}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="quickVerifyRecord(${r.record_id})">Verify ↗</button>
          </td>
        `;
        recordsTableBody.appendChild(row);
      });
    } catch (e) {
      console.warn("Audit records error:", e);
    }
  }

  window.quickVerifyRecord = function(recordId) {
    verifyRecordId.value = recordId;
    actionVerifyOrig.click();
    document.querySelector('[data-tab="tab-verify"]').click();
  };

  if (refreshRecordsBtn) refreshRecordsBtn.addEventListener("click", fetchAuditRecords);
});
