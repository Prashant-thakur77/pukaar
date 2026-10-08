package com.pukaar.pukaar.android.ui

import androidx.arch.core.executor.testing.InstantTaskExecutorRule
import com.pukaar.pukaar.android.data.PukaarRepository
import com.pukaar.pukaar.android.data.Pukaar AIOnDevice
import com.pukaar.pukaar.android.data.PendingReportEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.verifyBlocking
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class MainViewModelTest {

    @get:Rule
    val instantTaskExecutorRule = InstantTaskExecutorRule()

    private val testDispatcher = StandardTestDispatcher()

    private lateinit var repository: PukaarRepository
    private lateinit var pukaar-ai: Pukaar AIOnDevice

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        repository = mock {
            on { currentBaseUrl() } doReturn "http://localhost/api/"
            on { observePendingReports() } doReturn flowOf(emptyList<PendingReportEntity>())
        }
        pukaar-ai = mock()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `submitReport with available pukaar-ai sets parserSource pukaar-ai-android and skips backend`() = runTest(testDispatcher) {
        whenever(pukaar-ai.isAvailable()).thenReturn(true)
        whenever(pukaar-ai.structureReport(any())).thenReturn(
            "{\"water_level_category\":\"critical\"," +
                "\"trend\":\"rising\"," +
                "\"road_status\":\"blocked\"," +
                "\"bridge_status\":\"unknown\"," +
                "\"urgency\":\"critical\"," +
                "\"summary\":\"cruzo la marca\"," +
                "\"confidence\":0.9}"
        )

        val viewModel = MainViewModel(repository, pukaar-ai)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = false,
        )
        advanceUntilIdle()

        val result = viewModel.siteState.value.reportResult
        assertNotNull("expected report envelope to be populated", result)
        assertEquals("pukaar-ai-android", result!!.parsed.parserSource)
        assertEquals("Reporte estructurado localmente con Pukaar AI.", viewModel.siteState.value.message)
        verifyBlocking(repository, never()) {
            submitOrQueueReport(any(), any(), any(), any(), any())
        }
    }

    @Test
    fun `submitReport with available pukaar-ai but null structuring sets error and skips backend`() = runTest(testDispatcher) {
        whenever(pukaar-ai.isAvailable()).thenReturn(true)
        whenever(pukaar-ai.structureReport(any())).thenReturn(null)

        val viewModel = MainViewModel(repository, pukaar-ai)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = false,
        )
        advanceUntilIdle()

        assertNull(viewModel.siteState.value.reportResult)
        assertEquals(
            "Pukaar AI local no disponible — usá conexión a servidor.",
            viewModel.siteState.value.error,
        )
        assertFalse(viewModel.siteState.value.isSubmitting)
        verifyBlocking(repository, never()) {
            submitOrQueueReport(any(), any(), any(), any(), any())
        }
    }

    @Test
    fun `submitReport falls through to repository when pukaar-ai is null`() = runTest(testDispatcher) {
        val viewModel = MainViewModel(repository, pukaar-ai = null)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = true,
        )
        advanceUntilIdle()

        verifyBlocking(repository) {
            submitOrQueueReport("site-1", "Op", "brigadista", "el agua subio", true)
        }
    }

    @Test
    fun `submitReport falls through to repository when pukaar-ai is not available`() = runTest(testDispatcher) {
        whenever(pukaar-ai.isAvailable()).thenReturn(false)

        val viewModel = MainViewModel(repository, pukaar-ai)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = false,
        )
        advanceUntilIdle()

        verifyBlocking(repository) {
            submitOrQueueReport("site-1", "Op", "brigadista", "el agua subio", false)
        }
    }
}
