# Naming Conventions

## Variables

Use descriptive, domain-specific names with units where applicable:

```
GOOD: meca_pickup_position, ot2_pipette_volume_ul, wafer_batch_count
BAD:  pos, vol, cnt
```

## Classes

Include robot type and purpose in class names:

```
GOOD: MecaPickupService, OT2ProtocolRunner, CarouselStateManager
BAD:  Service1, Runner, Manager
```

## Functions

Use verb_noun pattern describing the action:

```
GOOD: execute_pickup_sequence, get_robot_status, acquire_resource_lock
BAD:  do_it, process, handle
```
