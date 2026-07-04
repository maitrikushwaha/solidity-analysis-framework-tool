pragma solidity ^0.4.25;


contract TokenTimelock {

  uint256 public releaseTime;

  function release() public returns (bool) {
    require(block.timestamp >= releaseTime);
    return true;
  }
}
