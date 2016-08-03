angular.module('aiddataDET')
.controller('StatusCtrl', function($stateParams, $scope, request, datasets) {
  $scope.id = $stateParams.id;
  $scope.request = request;

  $scope.getDataset = function (query) {
    console.log(request);
    var name = query.dataset || query.name;

    return _.find(datasets, {name : name });
  };
});
