/*
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This software may be used and distributed according to the terms of the
 * GNU General Public License version 2.
 */

#include "eden/fs/utils/Thread.h"
#include <pthread.h>

namespace facebook {
namespace eden {

void disablePthreadCancellation() {
  int oldstate;
  pthread_setcancelstate(PTHREAD_CANCEL_DISABLE, &oldstate);
  int oldtype;
  pthread_setcanceltype(PTHREAD_CANCEL_ASYNCHRONOUS, &oldtype);
}

} // namespace eden
} // namespace facebook
