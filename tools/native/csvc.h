#pragma once
#include "3ds.h"
enum ServiceOp { SERVICEOP_STEAL_CLIENT_SESSION = 0 };
Result svcControlService(ServiceOp, ...);
