pragma solidity ^0.4.25;


contract FsTKerWallet {

  function callContract(address to, bytes data) public payable returns (bool) {
    require(to.call.value(msg.value)(data));
    return true;
  }
}
