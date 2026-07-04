pragma solidity ^0.4.25;

contract LCBrixTokenCrowdsale {
  uint256 public deadline = 1518652800;
  bool public crowdsaleClosed = false;

  function recalcFlags() public {
    if (block.timestamp >= deadline)
        crowdsaleClosed = true;
    return;
  }
}