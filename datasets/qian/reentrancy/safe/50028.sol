pragma solidity ^0.4.25;


contract FDC {

    address public foundationWallet;

    address public owner;
    modifier onlyOwner() {
        require(msg.sender == owner);
        _;
    }

    function empty() onlyOwner returns(bool) {
        return foundationWallet.call.value(this.balance)();
    }
}

