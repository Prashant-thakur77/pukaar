package com.pukaar.pukaar.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import coil.compose.AsyncImage
import com.pukaar.pukaar.android.data.AlertSummary
import com.pukaar.pukaar.android.data.CalibrationPayload
import com.pukaar.pukaar.android.data.PendingReportEntity

private val Emerald = Color(0xFF0D3B2A)
private val River = Color(0xFF1476B8)
private val Clay = Color(0xFFB45F22)
private val Sand = Color(0xFFF3E9D2)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PukaarApp(viewModel: MainViewModel) {
    val navController = rememberNavController()
    val dashboard by viewModel.dashboard.collectAsState()
    val siteState by viewModel.siteState.collectAsState()
    val pendingReports by viewModel.pendingReports.collectAsState()
    val serverUrl by viewModel.serverUrl.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    LaunchedEffect(dashboard.error, siteState.message, siteState.error) {
        listOfNotNull(dashboard.error, siteState.message, siteState.error).firstOrNull()?.let {
            snackbarHostState.showSnackbar(it)
        }
    }

    MaterialTheme {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbarHostState) },
            bottomBar = {
                NavigationBar {
                    NavigationBarItem(
                        selected = currentRoute == "dashboard",
                        onClick = { navController.navigate("dashboard") },
                        label = { Text("Dashboard") },
                        icon = { Icon(Icons.Rounded.Refresh, null) },
                    )
                    NavigationBarItem(
                        selected = currentRoute == "queue",
                        onClick = { navController.navigate("queue") },
                        label = { Text("Queue") },
                        icon = { Icon(Icons.Rounded.CloudUpload, null) },
                    )
                    NavigationBarItem(
                        selected = currentRoute == "settings",
                        onClick = { navController.navigate("settings") },
                        label = { Text("Settings") },
                        icon = { Icon(Icons.Rounded.Save, null) },
                    )
                }
            },
        ) { innerPadding ->
            NavHost(
                navController = navController,
                startDestination = "dashboard",
                modifier = Modifier.padding(innerPadding),
            ) {
                composable("dashboard") {
                    DashboardScreen(
                        state = dashboard,
                        queueCount = pendingReports.size,
                        onRefresh = viewModel::refreshDashboard,
                        onOpenSite = { navController.navigate("site/$it") },
                    )
                }
                composable("queue") {
                    QueueScreen(
                        reports = pendingReports,
                        onFlush = viewModel::flushPendingReports,
                    )
                }
                composable("settings") {
                    SettingsScreen(
                        serverUrl = serverUrl,
                        onSaveServerUrl = viewModel::updateServerUrl,
                        onSetBackendConnectivity = viewModel::setBackendConnectivity,
                    )
                }
                composable(
                    route = "site/{siteId}",
                    arguments = listOf(navArgument("siteId") { type = NavType.StringType }),
                ) { backStack ->
                    val siteId = backStack.arguments?.getString("siteId").orEmpty()
                    LaunchedEffect(siteId) { viewModel.loadSite(siteId) }
                    SiteDetailScreen(
                        state = siteState,
                        onAnalyzeSample = { viewModel.analyzeSample(siteId) },
                        onRefreshHydromet = { viewModel.refreshSnapshot(siteId) },
                        onSubmitReport = { name, role, transcript, offline ->
                            viewModel.submitReport(siteId, name, role, transcript, offline)
                        },
                        onCalibrate = { navController.navigate("site/$siteId/calibration") },
                    )
                }
                composable(
                    route = "site/{siteId}/calibration",
                    arguments = listOf(navArgument("siteId") { type = NavType.StringType }),
                ) { backStack ->
                    val siteId = backStack.arguments?.getString("siteId").orEmpty()
                    CalibrationScreen(
                        state = siteState,
                        onSave = { payload -> viewModel.saveCalibration(siteId, payload) { navController.popBackStack() } },
                    )
                }
            }
        }
    }
}

@Composable
private fun DashboardScreen(
    state: DashboardState,
    queueCount: Int,
    onRefresh: () -> Unit,
    onOpenSite: (String) -> Unit,
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text("Pukaar Pukaar Android", style = MaterialTheme.typography.headlineMedium, color = Emerald, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(6.dp))
            Text("MVP Android conectado al backend real, con queue offline y operaciones sobre el clip fijo demo.")
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                StatusCard(
                    title = "LLM",
                    body = state.runtime?.llm?.let { "${it.model} | reachable=${it.reachable}" } ?: "Sin datos",
                    modifier = Modifier.fillMaxWidth(),
                )
                StatusCard(
                    title = "Queue",
                    body = "$queueCount pendientes",
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        item {
            Button(onClick = onRefresh) { Text(if (state.isLoading) "Refreshing..." else "Refresh dashboard") }
        }
        item {
            Text("Alertas", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        }
        items(state.alerts) { alert -> AlertCard(alert) }
        item {
            Text("Sitios", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        }
        items(state.sites) { site ->
            Card(modifier = Modifier.fillMaxWidth().clickable { onOpenSite(site.id) }) {
                Column(Modifier.padding(16.dp)) {
                    Text(site.name, fontWeight = FontWeight.Bold)
                    Text(site.region)
                    Text(site.id, style = MaterialTheme.typography.bodySmall, color = River)
                    site.description?.let {
                        Spacer(Modifier.height(6.dp))
                        Text(it, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

@Composable
private fun StatusCard(title: String, body: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier) {
        Column(Modifier.padding(16.dp)) {
            Text(title, fontWeight = FontWeight.Bold, color = River)
            Spacer(Modifier.height(8.dp))
            Text(body)
        }
    }
}

@Composable
private fun AlertCard(alert: AlertSummary) {
    val chipColor = when (alert.level) {
        "red" -> Color(0xFFB42318)
        "orange" -> Clay
        "yellow" -> Color(0xFFB08800)
        else -> Emerald
    }
    Card {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(onClick = {}, label = { Text(alert.level.uppercase()) })
                Box(Modifier.background(chipColor, RoundedCornerShape(999.dp)).padding(horizontal = 10.dp, vertical = 4.dp)) {
                    Text(alert.siteId, color = Color.White)
                }
            }
            Text(alert.summary, fontWeight = FontWeight.Medium)
            Text("score=${String.format("%.2f", alert.score)} | ${alert.createdAt}", style = MaterialTheme.typography.bodySmall)
            ReasoningPanel(alert)
        }
    }
}

@Composable
private fun ReasoningPanel(alert: AlertSummary) {
    val summary = alert.reasoningSummary ?: return
    var expanded by remember { mutableStateOf(false) }
    Column {
        TextButton(onClick = { expanded = !expanded }, contentPadding = PaddingValues(0.dp)) {
            Text(
                if (expanded) "Ocultar razonamiento de Pukaar AI" else "Razonamiento de Pukaar AI (${alert.reasoningModel ?: "local"})",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold,
            )
        }
        if (expanded) {
            Text(summary, style = MaterialTheme.typography.bodySmall)
            val chain = alert.reasoningChain
            if (!chain.isNullOrBlank()) {
                Text(
                    chain.trim('[', ']').replace("\"", ""),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun SiteDetailScreen(
    state: SiteScreenState,
    onAnalyzeSample: () -> Unit,
    onRefreshHydromet: () -> Unit,
    onSubmitReport: (String, String, String, Boolean) -> Unit,
    onCalibrate: () -> Unit,
) {
    var reporterName by rememberSaveable { mutableStateOf("Operador Android") }
    var reporterRole by rememberSaveable { mutableStateOf("brigadista") }
    var transcriptText by rememberSaveable { mutableStateOf("El agua ya cruzo la marca critica y trae barro, evacuar zona baja.") }
    var saveOffline by rememberSaveable { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(state.site?.name ?: "Site", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        state.site?.region?.let { Text(it) }
        state.site?.sampleFrameUrl?.let { frame ->
            AsyncImage(model = frame, contentDescription = "Calibration frame", modifier = Modifier.fillMaxWidth())
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onRefreshHydromet) {
                Icon(Icons.Rounded.Refresh, null)
                Spacer(Modifier.height(0.dp))
                Text("Hydromet")
            }
            Button(onClick = onAnalyzeSample) {
                Icon(Icons.Rounded.PlayArrow, null)
                Text("Analyze sample")
            }
            Button(onClick = onCalibrate) { Text("Calibrate") }
        }
        state.snapshot?.let { snapshot ->
            Card {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Hydromet snapshot", fontWeight = FontWeight.Bold)
                    Text(snapshot.summary)
                    Text("signal=${String.format("%.0f%%", snapshot.signalScore * 100)} | rain=${snapshot.precipitationMm} mm")
                }
            }
        }
        state.analysis?.let { analysis ->
            Card {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Node analysis", fontWeight = FontWeight.Bold)
                    Text("frames=${analysis.observation.framesAnalyzed} | ratio=${String.format("%.2f", analysis.observation.waterlineRatio)}")
                    Text("alert=${analysis.alert.level} | ${analysis.alert.summary}")
                    analysis.observation.evidenceFrameUrl?.let { evidence ->
                        AsyncImage(model = evidence, contentDescription = "Evidence frame", modifier = Modifier.fillMaxWidth())
                    }
                }
            }
        }
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Volunteer report", fontWeight = FontWeight.Bold)
                OutlinedTextField(value = reporterName, onValueChange = { reporterName = it }, label = { Text("Reporter name") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = reporterRole, onValueChange = { reporterRole = it }, label = { Text("Role") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = transcriptText, onValueChange = { transcriptText = it }, label = { Text("Transcript") }, modifier = Modifier.fillMaxWidth(), minLines = 4)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Switch(checked = saveOffline, onCheckedChange = { saveOffline = it })
                    Text("Force offline queue")
                }
                Button(onClick = { onSubmitReport(reporterName, reporterRole, transcriptText, saveOffline) }, enabled = !state.isSubmitting) {
                    Text(if (state.isSubmitting) "Submitting..." else "Send report")
                }
                state.reportResult?.let { result ->
                    Text("parser=${result.parsed.parserSource} | urgency=${result.parsed.urgency} | water=${result.parsed.waterLevelCategory}")
                    Text(result.alert.summary)
                }
            }
        }
    }
}

@Composable
private fun CalibrationScreen(
    state: SiteScreenState,
    onSave: (CalibrationPayload) -> Unit,
) {
    var width by rememberSaveable { mutableStateOf("980") }
    var roiTop by rememberSaveable { mutableStateOf("70") }
    var roiBottom by rememberSaveable { mutableStateOf("265") }
    var criticalY by rememberSaveable { mutableStateOf("118") }
    var referenceY by rememberSaveable { mutableStateOf("190") }
    var notes by rememberSaveable { mutableStateOf(state.calibration?.notes ?: "Android calibration update") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Calibration", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        state.site?.sampleFrameUrl?.let { AsyncImage(model = it, contentDescription = null, modifier = Modifier.fillMaxWidth()) }
        NumericField("Frame width", width) { width = it }
        NumericField("ROI top", roiTop) { roiTop = it }
        NumericField("ROI bottom", roiBottom) { roiBottom = it }
        NumericField("Critical Y", criticalY) { criticalY = it }
        NumericField("Reference Y", referenceY) { referenceY = it }
        OutlinedTextField(value = notes, onValueChange = { notes = it }, label = { Text("Notes") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
        Button(onClick = {
            val frameWidth = width.toIntOrNull() ?: 980
            val payload = CalibrationPayload(
                roiPolygon = listOf(listOf(0, roiTop.toIntOrNull() ?: 70), listOf(frameWidth, roiTop.toIntOrNull() ?: 70), listOf(frameWidth, roiBottom.toIntOrNull() ?: 265), listOf(0, roiBottom.toIntOrNull() ?: 265)),
                criticalLine = listOf(listOf(0, criticalY.toIntOrNull() ?: 118), listOf(frameWidth, criticalY.toIntOrNull() ?: 118)),
                referenceLine = listOf(listOf(0, referenceY.toIntOrNull() ?: 190), listOf(frameWidth, referenceY.toIntOrNull() ?: 190)),
                notes = notes,
            )
            onSave(payload)
        }) { Text("Save calibration") }
    }
}

@Composable
private fun NumericField(label: String, value: String, onValueChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun QueueScreen(reports: List<PendingReportEntity>, onFlush: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Offline queue", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Button(onClick = onFlush, enabled = reports.isNotEmpty()) { Text("Flush queue") }
        LazyColumn(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(reports) { report ->
                Card {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(report.siteId, fontWeight = FontWeight.Bold)
                        Text("${report.reporterName} | ${report.reporterRole}")
                        Text(report.transcriptText)
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    serverUrl: String,
    onSaveServerUrl: (String) -> Unit,
    onSetBackendConnectivity: (Boolean) -> Unit,
) {
    var editableUrl by rememberSaveable(serverUrl) { mutableStateOf(serverUrl) }
    var backendOnline by rememberSaveable { mutableStateOf(true) }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("Por defecto el emulador usa 10.0.2.2 para llegar al backend FastAPI local.")
        OutlinedTextField(value = editableUrl, onValueChange = { editableUrl = it }, label = { Text("API base URL") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { onSaveServerUrl(editableUrl) }) { Text("Save URL") }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Switch(checked = backendOnline, onCheckedChange = {
                backendOnline = it
                onSetBackendConnectivity(it)
            })
            Text("Backend connectivity toggle")
        }
    }
}
