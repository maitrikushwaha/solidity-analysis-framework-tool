pragma solidity ^0.4.25;


contract SendBalance {

    mapping (address => uint) userBalances ;

    address owner;
    modifier onlyOwner() {
        require(msg.sender == owner);
        _;
    }

    function withdrawBalance() onlyOwner {
        if (!(msg.sender.call.value(userBalances[msg.sender])())) { throw ; }
        userBalances[msg.sender] = 0;
    }
}
