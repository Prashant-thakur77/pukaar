package com.pukaar.pukaar.android

import android.app.Application
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.pukaar.pukaar.android.data.Pukaar AIOnDevice
import com.pukaar.pukaar.android.data.SyncQueuedReportsWorker

class PukaarApplication : Application() {
    val pukaar-ai: Pukaar AIOnDevice by lazy { Pukaar AIOnDevice(this) }

    override fun onCreate() {
        super.onCreate()
        val request = OneTimeWorkRequestBuilder<SyncQueuedReportsWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .build()
        WorkManager.getInstance(this).enqueueUniqueWork(
            "sync-pending-reports",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }
}
