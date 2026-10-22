package com.movix.tv.data.account

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class AccountApiTest {
    private val server = MockWebServer()
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
    private lateinit var api: AccountApi

    @Before
    fun setUp() {
        server.start()
        api = AccountApi(OkHttpClient(), json, server.url("/"))
    }

    @After
    fun tearDown() = server.close()

    // Compte VIP avec une clé datée : un ancien serveur renvoie `expiresAt` en
    // millisecondes (BIGINT). La lecture doit passer, sinon la liaison est perdue.
    @Test
    fun `poll approuvé lu avec une date VIP en nombre`() = runTest {
        server.enqueue(MockResponse.Builder().body("""{"status":"approved","token":"jwt","userType":"oauth","userId":"u1",
            "profileId":"p1","profile":{"id":"p1","name":"Alice","avatar":null,"ageRestriction":0},
            "vip":{"active":true,"expiresAt":1823758332500,"accessKey":"VIP-1"}}""").build())
        val poll = api.poll("d".repeat(43))
        assertEquals("approved", poll.status)
        assertEquals("jwt", poll.token)
        assertEquals("VIP-1", poll.vip?.accessKey)
    }

    @Test
    fun `poll approuvé lu avec une date VIP en ISO`() = runTest {
        server.enqueue(MockResponse.Builder().body("""{"status":"approved","token":"jwt","userType":"oauth","userId":"u1",
            "profileId":"p1","vip":{"active":true,"expiresAt":"2027-10-17T07:32:12.500Z","accessKey":"VIP-1"}}""").build())
        assertEquals("VIP-1", api.poll("d".repeat(43)).vip?.accessKey)
    }
}
