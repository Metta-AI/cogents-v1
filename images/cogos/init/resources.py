add_resource("lambda_slots", type="pool", capacity=5, metadata={"description": "Concurrent Lambda executor slots"})
add_resource("ecs_slots", type="pool", capacity=2, metadata={"description": "Concurrent ECS task slots"})
add_resource("channel_executor_slots", type="pool", capacity=10, metadata={"description": "Concurrent channel executor slots"})
