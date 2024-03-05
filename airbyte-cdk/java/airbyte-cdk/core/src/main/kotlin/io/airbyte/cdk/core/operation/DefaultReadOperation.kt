/*
 * Copyright (c) 2024 Airbyte, Inc., all rights reserved.
 */

package io.airbyte.cdk.core.operation

import io.airbyte.cdk.core.context.env.ConnectorConfigurationPropertySource
import io.airbyte.cdk.core.operation.executor.OperationExecutor
import io.airbyte.protocol.models.v0.AirbyteMessage
import io.github.oshai.kotlinlogging.KotlinLogging
import io.micronaut.context.annotation.Requires
import jakarta.inject.Named
import jakarta.inject.Singleton

private val logger = KotlinLogging.logger {}

@Singleton
@Named("readOperation")
@Requires(
    property = ConnectorConfigurationPropertySource.CONNECTOR_OPERATION,
    value = "read",
)
@Requires(env = ["source"])
class DefaultReadOperation(
    @Named("readOperationExecutor") private val operationExecutor: OperationExecutor,
) : Operation {
    override fun type(): OperationType {
        return OperationType.READ
    }

    override fun execute(): Result<AirbyteMessage?> {
        logger.info { "Using default read operation." }
        return operationExecutor.execute()
    }

    override fun requiresCatalog(): Boolean {
        return true
    }

    override fun requiresConfiguration(): Boolean {
        return true
    }
}
