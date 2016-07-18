angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $log, $stateParams, queryFactory) {
  $scope.filters = queryFactory.filters;
  $scope.searchData = {};
  $scope.dataset = {};
  $scope.totals = {};
  $scope.queryStructure = setQueryStructure();
  $scope.geography = $stateParams.boundary;
  $scope.requestData = { name: 'New Request', editing: false };

  $scope.removeFilter = function(filter, option) {
    queryFactory.toggleFilterOff(filter, option);
  };

  $scope.clearFilters = function () {
    // _.chain($scope.queryStructure)
    //   .filter({ optional: true })
    //   .each(function(param) { queryFactory.resetFilter(param.key); })
    //   .value();

    console.log($scope.searchData);
  };

  $rootScope.$on('filters:update', function(e, data) {
    $scope.searchData = data;
  });

  $rootScope.$on('filters:updated', function(e, data) {
    $scope.totals = _.pick(data, ['projects', 'locations']);

    // Being Redefined with each filters:updated event because it directly
    // references $scope vars which will need to be update
    $scope.queryStructure = setQueryStructure();
  });

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
  });

  function setQueryStructure () {
    return [
      { value: [ $scope.dataset.title ], pre: 'Extract data from ', optional: false },
      { value: [ $scope.geography ], pre: 'within ', optional: false },
      { value: $scope.searchData.donors, pre: 'given by ', optional: true, key: 'donors' },
      { value: $scope.searchData.ad_sector_names, pre: 'to promote ', optional: true, key: 'ad_sector_names' }
    ];
  }

  function init () {
    queryFactory.setBoundary($stateParams.boundary, $stateParams.subboundary);
  }
  init();
});
